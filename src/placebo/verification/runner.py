"""Subject-suite execution: the oracle at the centre of Placebo.

Every claim Placebo makes reduces to one deterministic question:

    Does the subject test suite fail when this specific fault is injected?

This module owns that question. It maintains an isolated workspace copy of the
subject, applies exactly one mutant at a time, runs pytest as a subprocess, and
classifies the outcome. Nothing here calls a model.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ..mutation.models import Mutant, MutantRun, MutantStatus

# pytest exit codes we treat as a usable signal.
_EXIT_OK = 0
_EXIT_TESTS_FAILED = 1
_EXIT_INTERRUPTED = 2
_EXIT_INTERNAL = 3
_EXIT_USAGE = 4
_EXIT_NO_TESTS = 5

_FAILED_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)
_COLLECT_ERROR_RE = re.compile(
    r"(errors? during collection|ImportError while loading conftest|INTERNALERROR)",
    re.IGNORECASE,
)


@dataclass
class RunResult:
    """Raw outcome of one pytest invocation."""

    returncode: int
    duration_s: float
    stdout: str
    stderr: str
    failing_tests: list[str] = field(default_factory=list)
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.returncode == _EXIT_OK and not self.timed_out

    @property
    def collection_broken(self) -> bool:
        """True when pytest could not even load the tests."""
        if self.timed_out:
            return False
        if self.returncode in (_EXIT_INTERNAL, _EXIT_USAGE, _EXIT_NO_TESTS):
            return True
        return bool(_COLLECT_ERROR_RE.search(self.stdout + self.stderr))


class SubjectRunner:
    """Runs the vendored subject suite inside a disposable workspace copy.

    The workspace is created once and reused. A mutant is applied by rewriting a
    single file and is always restored afterwards, so runs cannot leak into one
    another.
    """

    def __init__(
        self,
        subject_root: Path,
        workspace: Path,
        test_dir: str = "tests",
        timeout_s: int = 300,
    ) -> None:
        self.subject_root = Path(subject_root).resolve()
        self.workspace = Path(workspace).resolve()
        self.test_dir = test_dir
        self.timeout_s = timeout_s
        self._originals: dict[str, str] = {}

    # -- workspace ---------------------------------------------------------

    @staticmethod
    def _force_remove(path: Path) -> None:
        """rmtree that survives Windows read-only files and stale handles."""

        def on_error(func, target, _exc):  # pragma: no cover - platform detail
            try:
                os.chmod(target, 0o700)
                func(target)
            except OSError:
                pass

        for _ in range(3):
            if not path.exists():
                return
            shutil.rmtree(path, onerror=on_error)
            if not path.exists():
                return
            time.sleep(0.2)

    def prepare(self) -> None:
        """Create a clean workspace copy of the subject."""
        self._force_remove(self.workspace)
        self.workspace.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            self.subject_root,
            self.workspace,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
            dirs_exist_ok=True,
        )

    def _read(self, relpath: str) -> str:
        return (self.workspace / relpath).read_text(encoding="utf-8")

    def _write(self, relpath: str, text: str) -> None:
        (self.workspace / relpath).write_text(text, encoding="utf-8", newline="")

    @contextmanager
    def mutated(self, mutant: Mutant):
        """Apply exactly one mutant for the duration of the block."""
        original = self._read(mutant.file)
        try:
            self._write(mutant.file, mutant.apply(original))
            yield
        finally:
            self._write(mutant.file, original)

    @contextmanager
    def extra_tests(self, files: dict[str, str]):
        """Temporarily add candidate test files, keyed by workspace-relative path."""
        written: list[Path] = []
        try:
            for rel, content in files.items():
                path = self.workspace / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="")
                written.append(path)
            yield
        finally:
            for path in written:
                path.unlink(missing_ok=True)
            for cache in self.workspace.rglob("__pycache__"):
                shutil.rmtree(cache, ignore_errors=True)

    # -- execution ---------------------------------------------------------

    def run_suite(
        self, selection: list[str] | None = None, tb: str = "no"
    ) -> RunResult:
        """Run the subject suite (or a selection of node ids / files).

        ``tb`` controls traceback detail. Census runs use ``no`` for speed, but
        the admission gate uses ``short`` so the rejection feedback handed back
        to the agent contains the actual assertion values it got wrong.
        """
        target = selection if selection else [self.test_dir]
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *target,
            "-q",
            f"--tb={tb}",
            "-rfE",
            "-p",
            "no:cacheprovider",
            "--no-header",
            "-o",
            "addopts=",
        ]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.workspace)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"

        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            return RunResult(
                returncode=-1,
                duration_s=time.perf_counter() - start,
                stdout=(exc.stdout or b"").decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or ""),
                stderr="TIMEOUT",
                timed_out=True,
            )
        duration = time.perf_counter() - start
        return RunResult(
            returncode=proc.returncode,
            duration_s=duration,
            stdout=proc.stdout,
            stderr=proc.stderr,
            failing_tests=sorted(set(_FAILED_RE.findall(proc.stdout))),
        )

    # -- mutant classification --------------------------------------------

    def check_baseline(self) -> RunResult:
        """The clean suite must be green before any mutant result is meaningful."""
        return self.run_suite()

    def run_mutant(
        self,
        mutant: Mutant,
        selection: list[str] | None = None,
        extra: dict[str, str] | None = None,
    ) -> MutantRun:
        """Execute the suite against one mutant and classify the outcome.

        SURVIVED means the fault is present and every evaluated test still
        passes. It is a candidate sensitivity gap; equivalence and contract
        relevance still require triage before calling it a real defect gap.
        """
        with self.mutated(mutant):
            if extra:
                with self.extra_tests(extra):
                    result = self.run_suite(selection)
            else:
                result = self.run_suite(selection)

        if result.timed_out:
            status = MutantStatus.TIMEOUT
        elif result.collection_broken:
            # The mutant broke import/collection rather than behavior. This is
            # not evidence that the suite detects the fault.
            status = MutantStatus.INVALID
        elif result.returncode == _EXIT_OK:
            status = MutantStatus.SURVIVED
        elif result.returncode == _EXIT_TESTS_FAILED:
            status = MutantStatus.KILLED
        else:
            status = MutantStatus.ERROR

        return MutantRun(
            mutant_id=mutant.id,
            status=status,
            duration_s=round(result.duration_s, 3),
            failing_tests=result.failing_tests[:10],
            returncode=result.returncode,
            detail=result.stderr[-400:] if status is MutantStatus.ERROR else "",
        )

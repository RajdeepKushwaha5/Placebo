"""Coverage-based test selection.

The idea
--------
A test can only detect a fault if it executes the mutated line. Running every
test against every fault therefore spends most of its time proving the
impossible. With a per-test line map, each fault runs only the tests that
reach it.

Why this is safe
----------------
Selection is an optimisation, and an optimisation that loses a kill is a
correctness bug, so the rule is deliberately asymmetric: a test is excluded
only when there is positive evidence it never reaches the line. Anything
unclear selects the whole suite.

Two cases force the conservative path, and both are real rather than
theoretical:

* **Import-time lines.** ``coverage`` attributes lines executed while importing
  the module to no test at all, reporting an empty context. A ``def`` line, a
  module-level constant and a decorator all look like that. Mutating one can
  change behaviour for every test, so an unattributed line selects everything.
* **Unseen lines.** A line absent from the map was not executed during the
  mapping run. That usually means no test reaches it, but it also happens when
  the mapping run itself was incomplete, so it selects everything too.

The map is built once per (subject, patch) and cached with the rest of the
audit, so its cost is paid on the first run only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .mutation.models import Mutant

# "tests/test_m.py::test_add|run" -> the test's function name.
_CONTEXT = re.compile(r"::([A-Za-z_]\w*)")


@dataclass
class CoverageMap:
    """Which tests execute which lines of the subject.

    ``lines`` maps a POSIX subject-relative path to {line number: {test names}}.
    An empty set of names means the line ran, but not inside any test.
    """

    lines: dict[str, dict[int, set[str]]] = field(default_factory=dict)
    all_tests: set[str] = field(default_factory=set)
    complete: bool = True

    def tests_for(self, mutant: Mutant) -> set[str]:
        """Tests that could possibly detect this fault.

        Returns every known test unless the mutated line is positively
        attributed to a smaller set.
        """
        if not self.complete or not self.all_tests:
            return set(self.all_tests)
        covering = self.lines.get(mutant.file, {}).get(mutant.lineno)
        if not covering:
            # Absent, or present but attributed to no test (import time).
            return set(self.all_tests)
        return set(covering)

    def reduction(self, faults: list[Mutant]) -> float:
        """Fraction of test executions this map avoids across a fault corpus.

        Reported rather than assumed: a map that saves nothing should say so.
        """
        if not self.all_tests or not faults:
            return 0.0
        full = len(faults) * len(self.all_tests)
        selected = sum(len(self.tests_for(f)) for f in faults)
        return round(1 - (selected / full), 4)

    def to_dict(self) -> dict:
        return {
            "files": len(self.lines),
            "tests": len(self.all_tests),
            "attributed_lines": sum(
                1 for per_file in self.lines.values()
                for names in per_file.values() if names
            ),
            "complete": self.complete,
        }


def parse_coverage_json(payload: dict, tests: set[str]) -> CoverageMap:
    """Turn ``coverage json --show-contexts`` output into a CoverageMap.

    Paths are normalised to POSIX because mutant ids address files that way,
    and a Windows-style key would silently match nothing.
    """
    result = CoverageMap(all_tests=set(tests))
    for raw_path, info in (payload.get("files") or {}).items():
        path = raw_path.replace("\\", "/")
        per_file: dict[int, set[str]] = {}
        for raw_line, contexts in (info.get("contexts") or {}).items():
            try:
                line = int(raw_line)
            except ValueError:  # pragma: no cover - defensive
                continue
            names = set()
            for context in contexts:
                match = _CONTEXT.search(context or "")
                if match:
                    names.add(match.group(1))
            per_file[line] = names & tests
        if per_file:
            result.lines[path] = per_file
    return result


def build_coverage_map(
    runner,
    suite_path: str,
    suite_code: str,
    tests: set[str],
    packages: list[str],
) -> CoverageMap:
    """Run the patch once under coverage and record per-test line contexts.

    One instrumented execution produces the whole map, because coverage's
    dynamic contexts attribute each line to the test that was running.

    Any failure to produce a map returns an incomplete one, which selects the
    full suite. Selection must never be the reason a fault goes undetected.
    """
    if not tests or not packages:
        return CoverageMap(all_tests=set(tests), complete=False)

    workspace = Path(runner.workspace)
    report = workspace / ".placebo-coverage.json"
    data_file = workspace / ".placebo-coverage"
    for stale in (report, data_file):
        stale.unlink(missing_ok=True)

    args = [
        "--cov-report=",
        "--cov-context=test",
        *[f"--cov={pkg}" for pkg in packages],
    ]
    env_marker = {"COVERAGE_FILE": str(data_file)}
    try:
        with runner.extra_tests({suite_path: suite_code}):
            _run_with_env(runner, [suite_path], args, env_marker)
        payload = _export(workspace, data_file, report)
    except Exception:  # pragma: no cover - instrumentation is best effort
        return CoverageMap(all_tests=set(tests), complete=False)
    finally:
        for stale in (report, data_file):
            stale.unlink(missing_ok=True)

    if payload is None:
        return CoverageMap(all_tests=set(tests), complete=False)
    return parse_coverage_json(payload, tests)


def _run_with_env(runner, selection, extra_args, env_extra):
    """Run the suite with additional environment variables.

    ``SubjectRunner`` owns its environment, so the coverage data file location
    is passed through ``os.environ`` for the duration of the call rather than
    by widening the runner's signature for one caller.
    """
    import os

    previous = {k: os.environ.get(k) for k in env_extra}
    os.environ.update(env_extra)
    try:
        return runner.run_suite(selection, extra_args=extra_args)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _export(workspace: Path, data_file: Path, report: Path) -> dict | None:
    """Convert the coverage data file into JSON with contexts."""
    import os
    import subprocess
    import sys

    if not any(workspace.glob(".placebo-coverage*")):
        return None
    env = dict(os.environ)
    env["COVERAGE_FILE"] = str(data_file)
    proc = subprocess.run(
        [sys.executable, "-m", "coverage", "json",
         "--show-contexts", "-o", str(report)],
        cwd=workspace, env=env, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not report.exists():
        return None
    return json.loads(report.read_text(encoding="utf-8"))


def load_or_build_coverage_map(
    runner,
    cache,
    subject_commit: str,
    suite_path: str,
    suite_code: str,
    tests: set[str],
    packages: list[str],
) -> CoverageMap:
    """Reuse a recorded map, or build and record one.

    Building the map is itself an instrumented execution, so it is cached on
    the same terms as everything else: the same subject, the same patch and
    the same environment give the same map.
    """
    from .cache import ResultCache

    key = ResultCache.key(
        subject_commit, "coverage-map", ResultCache.hash_patch(suite_code), [suite_path]
    )
    recorded = cache.get(key) if cache is not None else None
    if recorded is not None:
        restored = CoverageMap(
            all_tests=set(recorded["all_tests"]), complete=recorded["complete"]
        )
        restored.lines = {
            path: {int(line): set(names) for line, names in per_file.items()}
            for path, per_file in recorded["lines"].items()
        }
        return restored

    built = build_coverage_map(runner, suite_path, suite_code, tests, packages)
    if cache is not None and built.complete:
        cache.put(key, {
            "all_tests": sorted(built.all_tests),
            "complete": built.complete,
            "lines": {
                path: {str(line): sorted(names) for line, names in per_file.items()}
                for path, per_file in built.lines.items()
            },
        })
    return built

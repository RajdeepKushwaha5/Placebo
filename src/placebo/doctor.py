"""Preflight: can Placebo audit this repository, and if not, why not?

Every failure here is meant to be actionable. A repository that cannot be
audited should say which requirement it misses and what to do about it, rather
than producing a traceback halfway through a census.

Checks run in dependency order and stop reporting downstream results once a
prerequisite fails, because "test command not found" makes "suite is green"
meaningless rather than false.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import CONFIG_NAME, ConfigError, SubjectConfig, load, suggest


@dataclass
class Finding:
    """One preflight result."""

    name: str
    ok: bool
    detail: str = ""
    remedy: str = ""
    blocking: bool = True

    @property
    def symbol(self) -> str:
        if self.ok:
            return "OK  "
        return "FAIL" if self.blocking else "WARN"

    def to_dict(self) -> dict:
        return {
            "check": self.name,
            "ok": self.ok,
            "blocking": self.blocking,
            "detail": self.detail,
            "remedy": self.remedy,
        }


@dataclass
class Report:
    """The full preflight outcome for one repository."""

    root: Path
    config: SubjectConfig | None = None
    findings: list[Finding] = field(default_factory=list)

    def add(self, *args, **kwargs) -> Finding:
        finding = Finding(*args, **kwargs)
        self.findings.append(finding)
        return finding

    @property
    def supported(self) -> bool:
        return all(f.ok for f in self.findings if f.blocking)

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if not f.ok and not f.blocking]

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "supported": self.supported,
            "config": self.config.to_dict() if self.config else None,
            "findings": [f.to_dict() for f in self.findings],
        }


def _run(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Make the package importable the same way the runner does.
    env["PYTHONPATH"] = str(cwd)
    return subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
    )


def diagnose(root: Path, quick: bool = False) -> Report:
    """Run every preflight check against a repository."""
    root = Path(root).resolve()
    report = Report(root=root)

    if not root.is_dir():
        report.add("repository exists", False,
                   detail=f"{root} is not a directory",
                   remedy="Check the path.")
        return report
    report.add("repository exists", True, detail=str(root))

    # ---- configuration ---------------------------------------------------
    try:
        config = load(root)
        report.config = config
        report.add("configuration", True,
                   detail=f"{CONFIG_NAME}, language {config.language}")
    except ConfigError as exc:
        report.add("configuration", False, detail=str(exc),
                   remedy=f"Write a {CONFIG_NAME}; 'placebo doctor <repo> --init' "
                          f"prints a starting point inferred from the layout.")
        return report

    # ---- layout ----------------------------------------------------------
    missing_sources = [s for s in config.source_roots if not (root / s).exists()]
    report.add("source roots exist", not missing_sources,
               detail=", ".join(config.source_roots) or "none declared",
               remedy=f"Missing: {', '.join(missing_sources)}" if missing_sources else "")

    missing_tests = [t for t in config.test_roots if not (root / t).exists()]
    report.add("test roots exist", not missing_tests,
               detail=", ".join(config.test_roots),
               remedy=f"Missing: {', '.join(missing_tests)}" if missing_tests else "")

    # ---- mutation targets -------------------------------------------------
    targets = config.resolved_targets()
    report.add("mutation targets resolve", bool(targets),
               detail=f"{len(targets)} file(s)"
                      + (f": {targets[0]}" + (" ..." if len(targets) > 1 else "")
                         if targets else ""),
               remedy="No files matched 'mutation_targets'. Check the globs."
                      if not targets else "")

    # ---- the engine can parse them ---------------------------------------
    if targets:
        from .mutation.engine import enumerate_subject
        try:
            mutants = enumerate_subject(root, targets, config.commit or "working-tree")
            report.add("faults can be enumerated", bool(mutants),
                       detail=f"{len(mutants)} faults across "
                              f"{len({m.qualname for m in mutants})} functions",
                       remedy="The engine found no mutable code in the targets."
                              if not mutants else "")
        except (SyntaxError, FileNotFoundError, UnicodeDecodeError) as exc:
            report.add("faults can be enumerated", False, detail=f"{type(exc).__name__}: {exc}",
                       remedy="A target file could not be parsed as Python.")

    # ---- probe allowlist --------------------------------------------------
    report.add("probe allowlist declared", bool(config.import_names),
               detail=", ".join(config.import_names) or "none",
               remedy="Declare 'import_names'. Without it the oracle probe "
                      "rejects every expression and search cannot run.",
               blocking=False)

    # ---- test runner ------------------------------------------------------
    executable = config.test_command[0]
    resolved = executable if Path(executable).is_absolute() else shutil.which(executable)
    if executable in {"python", sys.executable}:
        resolved = sys.executable
    report.add("test command available", bool(resolved),
               detail=" ".join(config.test_command),
               remedy=f"'{executable}' is not on PATH." if not resolved else "")

    if quick or not resolved:
        return report

    # ---- the existing suite must be green --------------------------------
    command = list(config.test_command)
    if command[0] == "python":
        command[0] = sys.executable
    command.extend(config.test_roots)
    started = time.perf_counter()
    try:
        result = _run(command, root, timeout=max(config.timeout_seconds * 5, 300))
        elapsed = time.perf_counter() - started
        report.add("existing suite passes", result.returncode == 0,
                   detail=f"exit {result.returncode} in {elapsed:.1f}s",
                   remedy="Placebo measures which faults a green suite misses. "
                          "A red suite makes every verdict meaningless."
                          if result.returncode else "")
        # Speed matters because the census runs the suite once per fault.
        if result.returncode == 0:
            report.add("suite is fast enough for a census", elapsed < 30,
                       detail=f"{elapsed:.1f}s per run",
                       remedy=f"At {elapsed:.0f}s per run a full census costs "
                              f"roughly {elapsed * 150 / 60:.0f} minutes. Narrow "
                              f"'mutation_targets' or use a subset.",
                       blocking=False)
    except subprocess.TimeoutExpired:
        report.add("existing suite passes", False, detail="timed out",
                   remedy="The suite exceeded the timeout. Raise "
                          "'timeout_seconds' or narrow the test roots.")

    return report


def render(report: Report) -> str:
    """Human-readable preflight output."""
    lines = ["=" * 74,
             f"  PLACEBO DOCTOR  {report.root}",
             "=" * 74]
    for finding in report.findings:
        lines.append(f"  {finding.symbol}  {finding.name}"
                     + (f": {finding.detail}" if finding.detail else ""))
        # A remedy is advice for a problem, so it is noise on a passing check.
        if finding.remedy and not finding.ok:
            lines.append(f"        {finding.remedy}")
    lines.append("=" * 74)
    if report.supported:
        verdict = "SUPPORTED"
        if report.warnings:
            verdict += f" with {len(report.warnings)} warning(s)"
        lines.append(f"  {verdict}")
        lines.append("  Next: placebo census <repo>")
    else:
        blocking = [f for f in report.findings if f.blocking and not f.ok]
        lines.append(f"  NOT SUPPORTED: {len(blocking)} blocking problem(s)")
        lines.append("  Fix the FAIL lines above, then run doctor again.")
    lines.append("=" * 74)
    return "\n".join(lines)


def init_config(root: Path) -> str:
    """A starting config inferred from the repository layout."""
    return suggest(root)

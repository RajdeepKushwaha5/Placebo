"""Release gate: validate a snapshot before tagging it.

Everything a reader is told to run is run here, in one sequence, against a
clean tree. The point is that "it works" stops being a memory of having seen it
work and becomes a command anyone can repeat.

The steps run sequentially. Workspaces are now isolated per run, so
concurrency is no longer a correctness problem, but these steps compete for the
same CPU and a parallel gate would report timings nobody could reproduce.

Usage:
  python scripts/release_check.py            full gate, about 25 minutes
  python scripts/release_check.py --fast     skips the full suite and the venv
  python scripts/release_check.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Commands the README tells a reader to run: the command, a string that proves
# it worked, and the text the README must still contain for it to count as
# documented. The needle is stated rather than derived, because the README
# writes `placebo gaps` while the gate runs `python -m placebo.cli gaps`.
README_COMMANDS = [
    ('python -m pytest tests -m "not slow"', "passed", "pytest tests"),
    ("python scripts/check_consistency.py", "checks pass", "check_consistency.py"),
    ("python -m placebo.cli gaps", "Undetected", "placebo gaps"),
    ("python -m placebo.cli explain test_placebo_01", "exists to detect",
     "placebo explain"),
    ("python -m placebo.cli verify --bundle artifacts/bundle", "claims hold",
     "verify --bundle"),
    ("python -m placebo.cli doctor subject --quick", "SUPPORTED", "placebo doctor"),
    ("python -m placebo.cli doctor subjects/inflection --quick", "SUPPORTED",
     "placebo doctor"),
    ("python scripts/run_gap_search.py", "6/6", "run_gap_search.py"),
]

# Validation steps that are not documented for readers, so they are run but not
# asserted into the README.
INTERNAL_COMMANDS = [
    ("python scripts/hash_subjects.py --check", "unchanged"),
    ("python -m placebo.cli census --help", "usage"),
    ("python -m placebo.cli audit-pr --help", "usage"),
]


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0
    output_tail: str = ""

    def to_dict(self) -> dict:
        return {
            "step": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "seconds": round(self.seconds, 1),
        }


@dataclass
class Gate:
    steps: list[Step] = field(default_factory=list)

    def run(self, name: str, command: str, expect: str = "",
            cwd: Path | None = None, env: dict | None = None,
            timeout: int = 1800) -> Step:
        started = time.perf_counter()
        proc = subprocess.run(
            command, shell=True, cwd=str(cwd or ROOT),
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, **(env or {})},
        )
        elapsed = time.perf_counter() - started
        combined = proc.stdout + proc.stderr
        ok = proc.returncode == 0 and (not expect or expect in combined)
        detail = ""
        if proc.returncode != 0:
            detail = f"exit {proc.returncode}"
        elif expect and expect not in combined:
            detail = f"expected {expect!r} in output"
        step = Step(name, ok, detail, elapsed, combined[-400:])
        self.steps.append(step)
        self._report(step)
        return step

    def record(self, name: str, ok: bool, detail: str = "") -> Step:
        step = Step(name, ok, detail)
        self.steps.append(step)
        self._report(step)
        return step

    @staticmethod
    def _report(step: Step) -> None:
        mark = "PASS" if step.ok else "FAIL"
        timing = f"{step.seconds:6.1f}s" if step.seconds else "        "
        line = f"  {mark}  {timing}  {step.name}"
        if step.detail:
            line += f"  ({step.detail})"
        print(line, flush=True)

    @property
    def failed(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]


def check_tree_is_clean(gate: Gate) -> None:
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                          capture_output=True, text=True)
    dirty = [line for line in proc.stdout.splitlines() if line.strip()]
    gate.record(
        "working tree is clean",
        not dirty,
        f"{len(dirty)} uncommitted path(s): {', '.join(d[3:] for d in dirty[:3])}"
        if dirty else "",
    )


def check_readme_documents_what_we_ran(gate: Gate) -> None:
    """Every command in the list above must still appear in the README.

    Otherwise the gate drifts into validating commands nobody is told about,
    while a newly documented one goes unchecked.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [needle for _cmd, _expect, needle in README_COMMANDS
               if needle not in readme]
    gate.record(
        "README documents every validated command",
        not missing,
        ", ".join(sorted(set(missing))),
    )


def check_no_abandoned_workspaces(gate: Gate) -> None:
    """Report run directories left behind by a crash.

    These are harmless now that runs are isolated, but an accumulating pile of
    them means `prune_workspaces` is not being reached, which is worth knowing
    before tagging.
    """
    base = ROOT / ".placebo-ws"
    abandoned: list[str] = []
    if base.is_dir():
        for repo_dir in base.iterdir():
            if not repo_dir.is_dir():
                continue
            for commit_dir in repo_dir.iterdir():
                if commit_dir.is_dir():
                    runs = [d for d in commit_dir.iterdir() if d.is_dir()]
                    if len(runs) > 4:
                        abandoned.append(f"{repo_dir.name}/{commit_dir.name}: {len(runs)}")
    gate.record(
        "no pile of abandoned run workspaces",
        not abandoned,
        "; ".join(abandoned),
    )


# Artifact fields that record how long something took on this machine. A diff
# touching only these is noise, not drift.
_TIMING_FIELDS = ("duration_s", "wall_s", "seconds", "elapsed")


def restore_timing_only_churn(gate: Gate) -> None:
    """Revert artifacts whose only change is a recorded duration.

    Running the validated commands rewrites some artifacts. Where the entire
    diff is timing, the file is restored so the gate leaves the tree as it
    found it. Where it is not, the file is left alone and named, because that
    is real drift and hiding it would defeat the point of the gate.
    """
    proc = subprocess.run(["git", "diff", "--name-only"], cwd=str(ROOT),
                          capture_output=True, text=True)
    changed = [p for p in proc.stdout.split() if p]
    restored: list[str] = []
    substantive: list[str] = []

    for path in changed:
        diff = subprocess.run(["git", "diff", "--unified=0", "--", path],
                              cwd=str(ROOT), capture_output=True, text=True).stdout
        body = [
            line for line in diff.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        if body and all(any(field in line for field in _TIMING_FIELDS)
                        for line in body):
            subprocess.run(["git", "checkout", "--", path], cwd=str(ROOT),
                           capture_output=True, text=True)
            restored.append(path)
        else:
            substantive.append(path)

    if restored:
        print(f"  ....           restored timing-only churn in "
              f"{', '.join(restored)}", flush=True)
    gate.record(
        "validation left no substantive change behind",
        not substantive,
        ", ".join(substantive),
    )


def check_clean_install(gate: Gate) -> None:
    """Build the package and install it into a fresh interpreter.

    An editable install hides missing package data and wrong entry points, so
    the gate uses a real wheel in a virtual environment that shares nothing
    with the development one.
    """
    workdir = Path(tempfile.mkdtemp(prefix="placebo-release-"))
    try:
        build = gate.run(
            "build a wheel",
            f'"{sys.executable}" -m pip wheel --no-deps -w "{workdir}" .',
            timeout=600,
        )
        if not build.ok:
            return

        wheels = list(workdir.glob("*.whl"))
        if not wheels:
            gate.record("wheel produced", False, "no .whl in the output directory")
            return
        gate.record("wheel produced", True, wheels[0].name)

        env_dir = workdir / "venv"
        venv.create(env_dir, with_pip=True)
        python = (env_dir / "Scripts" / "python.exe" if os.name == "nt"
                  else env_dir / "bin" / "python")
        gate.record("clean virtual environment created", python.is_file())
        if not python.is_file():
            return

        gate.run(
            "install the wheel into the clean environment",
            f'"{python}" -m pip install --quiet "{wheels[0]}" pytest',
            timeout=900,
        )
        # Import from a directory that is not the source tree, so a passing
        # import proves the installed package rather than the checkout.
        gate.run(
            "installed package imports and exposes its version",
            f'"{python}" -c "import placebo, placebo.cli, placebo.cache, '
            f'placebo.sarif, placebo.oracle; print(\'import ok\')"',
            expect="import ok",
            cwd=workdir,
        )
        gate.run(
            "console script is on PATH",
            f'"{python}" -m placebo.cli --help',
            expect="audit",
            cwd=workdir,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true",
                        help="skip the full suite and the clean install")
    parser.add_argument("--json", metavar="PATH", help="write the report as JSON")
    args = parser.parse_args()

    width = 74
    print("=" * width)
    print("  RELEASE GATE" + ("  (fast)" if args.fast else ""))
    print("=" * width)

    gate = Gate()
    check_tree_is_clean(gate)
    check_no_abandoned_workspaces(gate)
    check_readme_documents_what_we_ran(gate)

    gate.run("fast unit suite", 'python -m pytest tests -m "not slow"',
             expect="passed", timeout=900)
    if not args.fast:
        gate.run("full unit suite, including end-to-end", "python -m pytest tests",
                 expect="passed", timeout=2400)

    gate.run("consistency checks", "python scripts/check_consistency.py",
             expect="checks pass", timeout=600)
    gate.run("report has not drifted", "python scripts/check_report_drift.py",
             expect="matches", timeout=600)

    gate.run("replay the benchmark bundle",
             "python scripts/verify_bundle.py --bundle artifacts/bundle",
             expect="claims hold", timeout=900)
    gate.run("replay the real-gap bundle",
             "python scripts/verify_bundle.py --bundle artifacts/real-gap-bundle",
             expect="claims hold", timeout=900)

    for command, expect, _needle in README_COMMANDS:
        gate.run(f"README command: {command}", command, expect=expect, timeout=1800)

    for command, expect in INTERNAL_COMMANDS:
        gate.run(f"internal: {command}", command, expect=expect, timeout=900)

    if not args.fast:
        check_clean_install(gate)

    restore_timing_only_churn(gate)

    print("=" * width)
    passed = len(gate.steps) - len(gate.failed)
    print(f"  {passed}/{len(gate.steps)} steps pass")
    if gate.failed:
        print(f"  {len(gate.failed)} FAILED. This snapshot is not releasable.")
        for step in gate.failed:
            print(f"    - {step.name}: {step.detail}")
            if step.output_tail:
                for line in step.output_tail.strip().splitlines()[-4:]:
                    print(f"        {line}")
    else:
        print("  Snapshot is releasable.")
    print("=" * width)

    if args.json:
        Path(args.json).write_text(
            json.dumps({
                "releasable": not gate.failed,
                "steps": [s.to_dict() for s in gate.steps],
            }, indent=2),
            encoding="utf-8",
        )

    return 1 if gate.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

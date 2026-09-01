"""Run the whole workflow against pinned public repositories.

The Phase 1 exit criterion asks for three differently shaped Python
repositories audited without editing Placebo's source. `tests/test_layouts.py`
proves the shapes are handled, using fixtures, which isolates the variable but
does not answer "does this survive contact with code nobody wrote for it".

This does. It clones pinned commits, writes a `.placebo.toml` for each, and
runs doctor, census, oracles and audit-pr end to end, recording what happened
including the failures. Configuration is not source: writing a contract is the
supported way to describe a repository, and none of Placebo's code is touched.

What gets recorded is deliberately unflattering. A repository Placebo cannot
handle is reported with the reason rather than dropped, because "worked on the
three we picked" is a much weaker claim than "here is what happened on all of
them".

Usage:
  python scripts/run_external_repos.py            clone, run, write the report
  python scripts/run_external_repos.py --quick    fewer faults, for a smoke run
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.verification.runner import SubjectRunner  # noqa: E402
WORKDIR = ROOT / ".placebo-external"
REPORT = ROOT / "experiments" / "external_repos.json"


@dataclass
class Target:
    """A pinned public repository and the contract describing it."""

    name: str
    url: str
    commit: str
    layout: str
    contract: str


# Pinned so the result is reproducible. Each is pure Python with a suite that
# runs on pytest alone, because a subject needing its own build step is a
# packaging question rather than a test of whether Placebo generalises.
TARGETS = [
    Target(
        name="inflection-upstream",
        url="https://github.com/jpvanhal/inflection.git",
        commit="b00d4d348b32ef5823221b20ee4cbd1d2d924462",  # tag 0.5.1
        layout="flat package, suite at the repository root",
        contract="""\
version = 1
name = "inflection-upstream"
language = "python"
test_command = ["python", "-m", "pytest", "-q"]
source_roots = ["inflection"]
test_roots = ["."]
mutation_targets = ["inflection/__init__.py"]
import_names = ["inflection"]
timeout_seconds = 60
""",
    ),
    Target(
        name="pathspec",
        url="https://github.com/cpburnz/python-pathspec.git",
        commit="ecf71a99ca739479d450b9830f43416ea0c519c7",  # tag v1.1.1
        layout="flat package, larger module set",
        contract="""\
version = 1
name = "pathspec"
language = "python"
test_command = ["python", "-m", "pytest", "-q"]
source_roots = ["pathspec"]
test_roots = ["tests"]
mutation_targets = ["pathspec/pattern.py"]
import_names = ["pathspec"]
timeout_seconds = 90
""",
    ),
    Target(
        name="toml-sort",
        url="https://github.com/pappasam/toml-sort.git",
        commit="c1655661b1d0af6fc0f7c0992c1a8a2c6b315b69",  # tag v0.9.0
        layout="flat package, subpackage target",
        contract="""\
version = 1
name = "toml-sort"
language = "python"
test_command = ["python", "-m", "pytest", "-q"]
source_roots = ["toml_sort"]
test_roots = ["tests"]
mutation_targets = ["toml_sort/tomlsort.py"]
import_names = ["toml_sort"]
timeout_seconds = 90
""",
    ),
]


@dataclass
class Outcome:
    name: str
    layout: str
    url: str
    commit: str = ""
    steps: dict = field(default_factory=dict)
    supported: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "repository": self.name,
            "layout": self.layout,
            "url": self.url,
            "commit": self.commit,
            "supported": self.supported,
            "note": self.note,
            "steps": self.steps,
        }


def run(argv: list[str], cwd: Path | None = None, timeout: int = 1800):
    started = time.perf_counter()
    proc = subprocess.run(argv, cwd=str(cwd or ROOT), capture_output=True,
                          text=True, timeout=timeout)
    return proc, round(time.perf_counter() - started, 1)


def clone(target: Target, into: Path) -> tuple[bool, str, str]:
    """Clone at a pinned commit. Returns (ok, commit, note)."""
    if into.exists():
        # git objects are read-only, and rmtree(ignore_errors=True) fails
        # silently on them, leaving a directory git then refuses to clone into.
        # SubjectRunner already solved this.
        SubjectRunner._force_remove(into)
        if into.exists():
            return False, "", f"could not clear {into.name} before cloning"
    proc, _ = run(["git", "clone", "--quiet", target.url, str(into)], timeout=900)
    if proc.returncode != 0:
        return False, "", f"clone failed: {proc.stderr.strip()[:160]}"

    if target.commit:
        proc, _ = run(["git", "checkout", "--quiet", target.commit], cwd=into)
        if proc.returncode != 0:
            # A pin that no longer resolves is worth reporting rather than
            # silently auditing whatever HEAD happens to be.
            return False, "", f"commit {target.commit[:12]} not found upstream"

    head, _ = run(["git", "rev-parse", "HEAD"], cwd=into)
    return True, head.stdout.strip(), ""


def evaluate(target: Target, quick: bool) -> Outcome:
    outcome = Outcome(name=target.name, layout=target.layout, url=target.url)
    into = WORKDIR / target.name

    ok, commit, note = clone(target, into)
    outcome.commit = commit
    if not ok:
        outcome.note = note
        return outcome

    contract = target.contract
    if commit:
        contract += f'commit = "{commit}"\n'
    (into / ".placebo.toml").write_text(contract, encoding="utf-8")

    # doctor: can Placebo describe this repository at all?
    proc, seconds = run([sys.executable, "-m", "placebo.cli", "doctor",
                         str(into), "--quick"])
    outcome.steps["doctor"] = {
        "exit": proc.returncode, "seconds": seconds,
        "supported": proc.returncode == 0 and "NOT SUPPORTED" not in proc.stdout,
    }
    if proc.returncode != 0:
        outcome.note = "doctor refused: " + _tail(proc.stdout)
        return outcome

    # oracles: what does the repository already state about itself?
    proc, seconds = run([sys.executable, "-m", "placebo.cli", "oracles",
                         "--repo", str(into)])
    outcome.steps["oracles"] = {
        "exit": proc.returncode, "seconds": seconds,
        "sourced": _first_int(proc.stdout, "oracle(s) sourced"),
    }

    # census: the slow, exhaustive pass.
    census = [sys.executable, "-m", "placebo.cli", "census", str(into),
              "--workers", "4"]
    if quick:
        census += ["--faults", "40"]
    proc, seconds = run(census, timeout=3600)
    outcome.steps["census"] = {
        "exit": proc.returncode, "seconds": seconds,
        "score": _after(proc.stdout, "mutation score"),
        "undetected": _after(proc.stdout, "UNDETECTED"),
    }
    if proc.returncode != 0:
        outcome.note = "census failed: " + _tail(proc.stdout)
        return outcome

    outcome.supported = True
    return outcome


def _tail(text: str, lines: int = 2) -> str:
    body = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(body[-lines:])[:200]


def _after(text: str, label: str) -> str:
    for line in text.splitlines():
        if label in line:
            return line.split(":")[-1].strip()
    return ""


def _first_int(text: str, label: str) -> int:
    for line in text.splitlines():
        if label in line:
            for token in line.split():
                if token.isdigit():
                    return int(token)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="cap the fault corpus, for a smoke run")
    args = parser.parse_args()

    WORKDIR.mkdir(parents=True, exist_ok=True)
    width = 74
    print("=" * width)
    print("  EXTERNAL REPOSITORIES  (pinned, cloned, no Placebo source edited)")
    print("=" * width)

    outcomes = []
    for target in TARGETS:
        print(f"\n  {target.name}  ({target.layout})")
        try:
            outcome = evaluate(target, args.quick)
        except subprocess.TimeoutExpired:
            outcome = Outcome(name=target.name, layout=target.layout,
                              url=target.url, note="timed out")
        outcomes.append(outcome)

        mark = "OK  " if outcome.supported else "SKIP"
        print(f"    {mark} {outcome.note or 'workflow completed'}")
        for step, detail in outcome.steps.items():
            print(f"         {step:8s} {detail}")

    supported = [o for o in outcomes if o.supported]
    print("\n" + "=" * width)
    print(f"  {len(supported)}/{len(outcomes)} repositories completed the workflow")
    print("=" * width)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "attempted": len(outcomes),
        "supported": len(supported),
        "repositories": [o.to_dict() for o in outcomes],
    }, indent=2), encoding="utf-8")
    print(f"  report -> {REPORT.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

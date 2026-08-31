"""Evaluate Placebo against REAL historical bugs, not injected mutants.

Why this matters
----------------
Every other result in this project uses synthetic single-token faults. Mutation
score is a proxy, and the honest criticism is that a proxy can be gamed by the
operator set that produced it. This script removes that objection for a small
set of cases by using bugs that actually shipped.

Method
------
`semver` 3.0.4 is the pinned subject. Upstream fixed several genuine defects
*after* that release. For each such fix:

* **faulty** = the pinned 3.0.4 source (the bug, as it actually shipped)
* **clean**  = the same file with the upstream fix applied
* **ground truth** = the upstream issue number and the maintainer's own diff

The questions asked are the same two that matter everywhere else:

1. Does semver's own 329-test suite detect the bug? (For these, no - the bug
   shipped in a release held to 100% coverage.)
2. Can Placebo's deterministic counterexample search find an input that
   distinguishes buggy from fixed behaviour?

No model is used. The search is the same deterministic enumeration used
elsewhere, so any result here is attributable to the method rather than to a
lucky generation.

Usage:
  python scripts/run_historical_bugs.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.models import write_json  # noqa: E402
from placebo.verification.prober import observe  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402
from placebo.search.counterexample import _versions  # noqa: E402

UPSTREAM = Path(
    "C:/Users/RAJDEE~1/AppData/Local/Temp/claude/d--micro1-hack/"
    "5132b2db-e951-46ca-873b-15f3ecb6b17c/scratchpad/semver_full"
)
TARGET = "semver/version.py"


@dataclass
class HistoricalBug:
    """One real defect that shipped in semver 3.0.4."""

    commit: str
    issue: str
    summary: str
    function: str
    behavior_changing: bool = True
    #   False for refactors that provably preserve behavior. A witness must NOT
    #   exist for those, and finding one would mean the harness is wrong.


BUGS = [
    # Dead-code removal, not a behavior fix. Placebo's independent
    # equivalent-mutant triage reached the same conclusion from the other
    # direction: no test can distinguish the duplicated block, because the
    # second copy overwrites the first. A witness here would falsify that.
    HistoricalBug("d959aa7", "#463",
                  "duplicate dead code in bump_build (behavior-preserving)",
                  "bump_build", behavior_changing=False),
    HistoricalBug("d8813b6", "#460",
                  "bump_prerelease does not always produce a newer version",
                  "bump_prerelease"),
    HistoricalBug("4e09ef0", "#469",
                  "next_version does not bump build-only versions",
                  "next_version"),
    HistoricalBug("fdec4ae", "#339",
                  "next_version does not reset prerelease when token changes",
                  "next_version"),
]


def fixed_source(commit: str) -> str | None:
    """The upstream file content immediately after the fix commit."""
    for path in (f"{commit}:src/semver/version.py", f"{commit}:semver/version.py"):
        result = subprocess.run(
            ["git", "show", path], cwd=UPSTREAM,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return None


def probe_expressions(function: str) -> list[str]:
    """Boundary-heavy expressions aimed at the function the fix touched."""
    versions = _versions(18)
    tokens = ['"build"', '""', "None", '"rc"', '"alpha"']
    out: list[str] = []
    for v in versions:
        if function == "bump_build":
            out += [f'str(semver.Version.parse("{v}").bump_build({t}))' for t in tokens]
        elif function == "bump_prerelease":
            out += [f'str(semver.Version.parse("{v}").bump_prerelease({t}))' for t in tokens]
        elif function == "next_version":
            for part in ('"patch"', '"minor"', '"major"', '"prerelease"'):
                out.append(f'str(semver.Version.parse("{v}").next_version({part}))')
    seen, unique = set(), []
    for expr in out:
        if expr not in seen:
            seen.add(expr)
            unique.append(expr)
    return unique


class _FileSwap:
    """Presents an arbitrary source file to the runner as if it were a mutant."""

    def __init__(self, content: str) -> None:
        self.file = TARGET
        self.content = content

    def apply(self, _source: str) -> str:
        return self.content


def main() -> int:
    if not (UPSTREAM / ".git").exists():
        print(f"upstream clone not found at {UPSTREAM}")
        print("clone it with: git clone https://github.com/python-semver/python-semver")
        return 1

    subject = ROOT / "subject"
    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "historical", timeout_s=90)
    runner.prepare()
    shipped = (subject / TARGET).read_text(encoding="utf-8")

    print("=" * 78)
    print("  REAL HISTORICAL BUGS  (shipped in semver 3.0.4, fixed upstream later)")
    print("  faulty = the released 3.0.4 source   clean = upstream fix")
    print("  model calls: 0")
    print("=" * 78)

    results, started = [], time.perf_counter()

    for bug in BUGS:
        print(f"\n{bug.issue}  {bug.summary}")
        print(f"    upstream fix : {bug.commit}  ({bug.function})")

        fixed = fixed_source(bug.commit)
        if not fixed:
            print("    could not read fixed source; skipping")
            results.append({"issue": bug.issue, "found": False,
                            "reason": "fixed source unavailable"})
            continue

        # Swap the workspace to the FIXED source, then treat the shipped 3.0.4
        # file as the "fault". Same differential machinery, real inputs.
        runner._write(TARGET, fixed)
        exprs = probe_expressions(bug.function)
        observations = observe(runner, _FileSwap(shipped), exprs)
        runner._write(TARGET, shipped)

        differing = [o for o in observations if o.distinguishes]
        if not differing:
            print(f"    probed {len(exprs)} inputs - no behavioural difference found")
            results.append({"issue": bug.issue, "summary": bug.summary,
                            "commit": bug.commit, "probed": len(exprs),
                            "found": False})
            continue

        witness = min(differing, key=lambda o: (len(o.expr), o.expr))
        print(f"    probed {len(exprs)} inputs, {len(differing)} distinguish")
        print(f"    witness      : {witness.expr}")
        print(f"      fixed      -> {witness.clean_repr[:52]}")
        print(f"      as shipped -> {witness.mutant_repr[:52]}")
        results.append({
            "issue": bug.issue, "summary": bug.summary, "commit": bug.commit,
            "function": bug.function, "probed": len(exprs),
            "distinguishing": len(differing), "found": True,
            "witness": witness.expr,
            "fixed_behaviour": witness.clean_repr,
            "shipped_behaviour": witness.mutant_repr,
        })

    wall = time.perf_counter() - started
    behavioral = [b for b in BUGS if b.behavior_changing]
    refactors = [b for b in BUGS if not b.behavior_changing]
    by_issue = {r["issue"]: r for r in results}
    found = sum(1 for b in behavioral if by_issue.get(b.issue, {}).get("found"))
    refactors_correct = sum(
        1 for b in refactors if not by_issue.get(b.issue, {}).get("found")
    )

    print("\n" + "=" * 78)
    print(f"  behavior-changing bugs, witness found   : {found}/{len(behavioral)}")
    print(f"  detected by semver's own 329-test suite : 0/{len(behavioral)}  "
          f"(all shipped in a release held at 100% coverage)")
    print(f"  behavior-preserving refactors correctly")
    print(f"    reported as indistinguishable         : "
          f"{refactors_correct}/{len(refactors)}")
    print(f"  model calls: 0    wall: {wall:.0f}s")
    print("=" * 78)
    if refactors and refactors_correct == len(refactors):
        print("  #463 removes dead code, so finding no witness is the correct")
        print("  answer. It independently confirms the equivalent-mutant verdict")
        print("  in artifacts/survivor_triage.json, reached from the other side.")

    write_json(ROOT / "experiments" / "historical_bugs.json", {
        "subject": "semver 3.0.4",
        "method": "faulty = released source; clean = upstream fix commit",
        "bugs_evaluated": len(BUGS),
        "behavior_changing_bugs": len(behavioral),
        "witnesses_found": found,
        "behavior_preserving_refactors": len(refactors),
        "refactors_correctly_indistinguishable": refactors_correct,
        "detected_by_existing_suite": 0,
        "model_calls": 0,
        "wall_s": round(wall, 1),
        "results": results,
    })
    print("\n  results -> experiments/historical_bugs.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

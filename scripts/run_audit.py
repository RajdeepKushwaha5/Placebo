"""Audit a test patch for marginal fault-detection value.

This is the product question, and it is the one coverage cannot answer:

    Of the tests in this patch, which ones detect a failure that nothing else
    already detects?

Every test is classified against two references at once — the repository's own
existing suite, and its sibling tests in the same patch — and the audit ends
with a minimized patch that provably loses no fault detection.

Usage:
  python scripts/run_audit.py --suite artifacts/suites/placebo_D.py
  python scripts/run_audit.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.audit.marginal import (  # noqa: E402
    Verdict,
    audit_suite,
    minimal_patch,
    sample_fault_corpus,
)
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]

SYMBOL = {
    Verdict.VALUABLE: "VALUABLE ",
    Verdict.REDUNDANT_WITH_SIBLING: "REDUNDANT(sibling)",
    Verdict.REDUNDANT_WITH_EXISTING: "REDUNDANT(existing)",
    Verdict.UNPROVEN: "UNPROVEN ",
    Verdict.HARMFUL: "HARMFUL  ",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--faults", type=int, default=0,
                        help="cap the fault corpus (0 = all enumerated faults)")
    args = parser.parse_args()

    subject = ROOT / "subject"
    census = json.loads((ROOT / "artifacts" / "census.json").read_text(encoding="utf-8"))
    existing_kills = {mid for mid, r in census.items() if r["status"] == "killed"}

    faults = enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)
    if args.faults:
        faults = sample_fault_corpus(faults, existing_kills, args.faults)

    if args.all:
        suites = sorted(p for p in (ROOT / "artifacts" / "suites").glob("*.py"))
    elif args.suite:
        suites = [ROOT / args.suite]
    else:
        suites = [ROOT / "artifacts" / "suites" / "placebo_D.py"]

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "audit", timeout_s=60)
    runner.prepare()

    all_reports = {}
    for suite_path in suites:
        code = suite_path.read_text(encoding="utf-8")
        name = suite_path.stem
        if "def test_" not in code:
            print(f"\n--- {name}: no tests to audit ---")
            continue

        print(f"\n{'=' * 78}")
        print(f"  AUDIT  {name}   ({len(faults)} faults in corpus)")
        print("=" * 78)

        audit = audit_suite(runner, name, code, faults, existing_kills)
        summary = audit.summary()

        for record in audit.tests:
            print(f"  {SYMBOL[record.verdict]:20s} {record.name}")
            print(f"      detects {len(record.detects):3d} faults | "
                  f"{len(record.novel):3d} missed by existing suite | "
                  f"{len(record.unique_novel):3d} uniquely")
            print(f"      {record.note}")

        print("-" * 78)
        v = summary["verdicts"]
        print(f"  tests audited            : {summary['tests_audited']}")
        print(f"  VALUABLE                 : {v['VALUABLE']}")
        print(f"  REDUNDANT (sibling)      : {v['REDUNDANT_WITH_SIBLING']}")
        print(f"  REDUNDANT (existing)     : {v['REDUNDANT_WITH_EXISTING']}")
        print(f"  UNPROVEN                 : {v['UNPROVEN']}")
        print(f"  HARMFUL                  : {v['HARMFUL']}")
        print(f"  gaps closed by patch     : {summary['gaps_closed_by_patch']}")
        print(f"  review burden reduction  : {summary['review_burden_reduction']:.0%}")

        minimized, kept, preserved = minimal_patch(audit, code)
        minimization = {}
        if minimized:
            out = ROOT / "artifacts" / "suites" / f"{name}.minimized.py"
            out.write_text(minimized, encoding="utf-8")
            print(f"\n  minimized patch          : {out.name} "
                  f"({len(kept)} of {summary['tests_audited']} tests)")

            # Do not take the set-cover argument on trust. Re-audit the
            # minimized patch and confirm by execution that it still detects
            # exactly the novel faults the full patch detected.
            recheck = audit_suite(runner, f"{name}.minimized", minimized,
                                  faults, existing_kills)
            still = {f for t in recheck.tests for f in t.novel}
            intact = still == preserved
            print(f"  re-audited minimized     : detects {len(still)} of "
                  f"{len(preserved)} novel faults -> "
                  f"{'NO LOSS (verified)' if intact else 'LOSS DETECTED'}")
            if not intact:
                print(f"    lost: {sorted(preserved - still)}")
            minimization = {
                "kept_tests": kept,
                "kept_count": len(kept),
                "original_count": summary["tests_audited"],
                "novel_faults_before": sorted(preserved),
                "novel_faults_after": sorted(still),
                "no_loss_verified": intact,
            }

        all_reports[name] = {
            "summary": summary,
            "tests": [t.to_dict() for t in audit.tests],
            "minimization": minimization,
        }

    write_json(ROOT / "experiments" / "audit.json", all_reports)
    print(f"\n  audit -> experiments/audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

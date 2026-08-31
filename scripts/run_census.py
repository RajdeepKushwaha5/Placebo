"""Enumerate mutants for the subject and run the full mutation census.

Writes:
  artifacts/mutants.json          full mutant inventory (content-hashed ids)
  artifacts/census.json           per-mutant killed/survived verdicts
  artifacts/census_summary.json   headline numbers

Usage:
  python scripts/run_census.py [--workers N]
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.census import run_census  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="debug: cap mutant count")
    args = parser.parse_args()

    subject = ROOT / "subject"
    artifacts = ROOT / "artifacts"

    print(f"Enumerating mutants in {TARGET_FILES} ...")
    mutants = enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)
    if args.limit:
        mutants = mutants[: args.limit]
    families = Counter(m.operator.value for m in mutants)
    print(f"  {len(mutants)} mutants across {len({m.qualname for m in mutants})} functions")
    for fam, n in families.most_common():
        print(f"    {fam:22s} {n:>4}")

    write_json(artifacts / "mutants.json", [m.to_dict() for m in mutants])

    print(f"\nRunning census with {args.workers} workers "
          f"(subject suite runs once per mutant) ...")
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    census = run_census(subject, ROOT / ".placebo-ws", mutants, workers=args.workers)

    summary = census.summary()
    summary["started_at"] = started
    summary["subject_commit"] = SUBJECT_COMMIT
    summary["target_files"] = TARGET_FILES
    summary["operator_families"] = dict(families)

    write_json(
        artifacts / "census.json",
        {mid: run.to_dict() for mid, run in sorted(census.runs.items())},
    )
    write_json(artifacts / "census_summary.json", summary)

    print("\n" + "=" * 62)
    print("  MUTATION CENSUS - subject's own suite vs. injected faults")
    print("=" * 62)
    print(f"  mutants enumerated : {summary['total_mutants']}")
    print(f"  scorable           : {summary['scorable']}")
    print(f"  killed             : {summary['killed']}")
    print(f"  SURVIVED (triage)  : {summary['survived']}")
    print(f"  mutation score     : {summary['mutation_score']:.1%}")
    print(f"  status breakdown   : {summary['status_counts']}")
    print(f"  wall time          : {summary['wall_s']}s")
    print("=" * 62)

    surv = [census.mutants[m] for m in census.survived]
    if surv:
        print("\n  Survivors by operator family:")
        for fam, n in Counter(m.operator.value for m in surv).most_common():
            print(f"    {fam:22s} {n:>4}")
        print("\n  First 15 survivors (candidate gaps; equivalence triage required):")
        for m in surv[:15]:
            print(f"    {m.id}  {m.label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

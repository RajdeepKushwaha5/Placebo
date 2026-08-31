"""Run the mutation census across every configured subject repository.

Generalization check. Placebo's first subject, semver, is dominated by boundary
and comparison logic - exactly the shape its mutation operators target. If the
method only worked there, that would be a benchmark artifact rather than a
result.

inflection is string-transformation logic (pluralize, camelize, underscore,
titleize) with a structurally different fault surface. Running the identical
pipeline on both is the cheapest honest test of whether the finding travels.

Usage:
  python scripts/run_multirepo_census.py
  python scripts/run_multirepo_census.py --only inflection
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

SUBJECTS = {
    "semver": {
        "root": "subject",
        "commit": "6adf8765f6e21910f1f0c13151ce84f32f8d431d",
        "targets": ["semver/version.py"],
        "tests": 329,
        "domain": "version comparison and boundary logic",
    },
    "inflection": {
        "root": "subjects/inflection",
        "commit": "b00d4d348b32ef5823221b20ee4cbd1d2d924462",
        "targets": ["inflection/__init__.py"],
        "tests": 455,
        "domain": "string transformation logic",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    names = [args.only] if args.only else list(SUBJECTS)
    report = {}

    for name in names:
        cfg = SUBJECTS[name]
        subject = ROOT / cfg["root"]
        targets = cfg["targets"]

        # Some projects keep the package at the repo root rather than src/.
        available = [t for t in targets if (subject / t).exists()]
        if not available:
            print(f"\n--- {name}: target file not found, skipping ---")
            continue

        print(f"\n{'=' * 70}")
        print(f"  SUBJECT {name}  ({cfg['domain']})")
        print("=" * 70)

        mutants = enumerate_subject(subject, available, cfg["commit"])
        families = Counter(m.operator.value for m in mutants)
        print(f"  {len(mutants)} faults across "
              f"{len({m.qualname for m in mutants})} functions")

        started = time.perf_counter()
        census = run_census(subject, ROOT / ".placebo-ws" / f"census-{name}",
                            mutants, workers=args.workers, progress=False)
        summary = census.summary()
        summary["subject"] = name
        summary["domain"] = cfg["domain"]
        summary["existing_tests"] = cfg["tests"]
        summary["operator_families"] = dict(families)
        summary["wall_s"] = round(time.perf_counter() - started, 1)

        print(f"  existing tests   : {cfg['tests']}")
        print(f"  faults           : {summary['scorable']}")
        print(f"  detected         : {summary['killed']}")
        print(f"  SURVIVED         : {summary['survived']}")
        print(f"  mutation score   : {summary['mutation_score']:.1%}")
        print(f"  wall             : {summary['wall_s']}s")

        write_json(ROOT / "artifacts" / f"census_{name}.json",
                   {mid: run.to_dict() for mid, run in sorted(census.runs.items())})
        report[name] = summary

    if len(report) > 1:
        print(f"\n{'=' * 70}")
        print("  CROSS-REPOSITORY COMPARISON")
        print("=" * 70)
        print(f"  {'subject':<12}{'tests':>7}{'faults':>8}{'survived':>10}"
              f"{'score':>9}  domain")
        for name, s in report.items():
            print(f"  {name:<12}{s['existing_tests']:>7}{s['scorable']:>8}"
                  f"{s['survived']:>10}{s['mutation_score']:>8.1%}  {s['domain']}")
        print("=" * 70)

    write_json(ROOT / "experiments" / "multirepo_census.json", report)
    print("\n  results -> experiments/multirepo_census.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

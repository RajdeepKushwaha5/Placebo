"""Analyze blinded reviewer ratings.

Run only after every reviewer has returned a completed form. Reads
`artifacts/review-study/ratings/*.json`, joins them to `key.json`, and reports
per-condition medians with a paired comparison across reviewers.

No ratings have been collected, so this script currently reports that and exits.
It exists so the analysis is fixed *before* any data arrives, which is the point
of pre-registering an instrument.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "artifacts" / "review-study"


def main() -> int:
    ratings_dir = STUDY / "ratings"
    files = sorted(ratings_dir.glob("*.json")) if ratings_dir.exists() else []
    if not files:
        print("No reviewer ratings collected.")
        print(f"Expected: {ratings_dir.relative_to(ROOT)}/<reviewer>.json")
        print("The instrument is built; the study has not been run. No human")
        print("acceptance numbers are claimed anywhere in this project.")
        return 0

    key = json.loads((STUDY / "key.json").read_text(encoding="utf-8"))
    by_condition: dict[str, list[float]] = {}
    for path in files:
        for label, scores in json.loads(path.read_text(encoding="utf-8")).items():
            condition = key.get(label, "unknown")
            by_condition.setdefault(condition, []).append(scores["would_merge"])

    print(f"{len(files)} reviewer(s)\n")
    for condition, values in sorted(by_condition.items()):
        print(f"  {condition:<20} median merge score "
              f"{statistics.median(values):.2f}  n={len(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

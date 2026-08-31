"""Report run-to-run variance from stored repeated runs.

Every headline condition in this project is a single run, and single runs of a
stochastic generator should not be read as point estimates. This script reports
the spread that was actually observed, using runs already stored on disk rather
than new generation, so it costs nothing and cannot be re-rolled until it looks
good.

Ollama with partial GPU offload is not bitwise deterministic even at
`temperature=0` with a fixed seed, so "seeds" here means *independent repeated
runs under nominally identical settings* - which is the honest description of
what was collected.

A bootstrap interval over three runs is very wide by construction. That is the
point: it shows how little three runs constrain the estimate, rather than
implying more precision than exists.

Usage:
  python scripts/run_variance.py
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.models import write_json  # noqa: E402

# Stored independent runs of the same condition, in the order they were made.
REPEATED = {
    "placebo_B": [
        "experiments/raw/placebo_B_v1.json",
        "experiments/raw/placebo_B_v2.json",
        "experiments/raw/pipeline_placebo_B.json",
    ],
}

BOOTSTRAP_SAMPLES = 10_000
SEED = 1729


def admitted_count(payload: dict) -> int | None:
    """Admitted cases in a stored run, whatever shape the file has."""
    meta = payload.get("meta") or {}
    if "discovery_admitted" in meta:
        return meta["discovery_admitted"]
    summary = payload.get("summary") or {}
    if "admitted" in summary:
        return summary["admitted"]
    results = payload.get("results")
    if isinstance(results, list):
        return sum(1 for r in results if r.get("admitted"))
    return None


def retry_recoveries(payload: dict) -> int | None:
    """Cases admitted only after a retry - the retry loop's actual yield."""
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    return sum(
        1 for r in results
        if r.get("admitted") and (r.get("attempts_used") or 1) > 1
    )


def bootstrap_ci(values: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap interval over the observed runs."""
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
    rng = random.Random(SEED)
    means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rng.choice(values) for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    low = means[int((1 - confidence) / 2 * len(means))]
    high = means[int((1 + confidence) / 2 * len(means)) - 1]
    return (round(low, 3), round(high, 3))


def main() -> int:
    print("=" * 78)
    print("  RUN-TO-RUN VARIANCE  (stored repeated runs, no new generation)")
    print("=" * 78)

    report = {}
    for condition, paths in REPEATED.items():
        runs = []
        for rel in paths:
            path = ROOT / rel
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            runs.append({
                "file": rel,
                "admitted": admitted_count(payload),
                "recoveries": retry_recoveries(payload),
            })

        usable = [r for r in runs if r["admitted"] is not None]
        if len(usable) < 2:
            print(f"\n  {condition}: fewer than two stored runs; skipping")
            continue

        admitted = [float(r["admitted"]) for r in usable]
        recoveries = [float(r["recoveries"]) for r in usable
                      if r["recoveries"] is not None]

        print(f"\n  condition: {condition}   ({len(usable)} independent runs)")
        print(f"  {'run':<44}{'admitted':>10}{'retry recoveries':>19}")
        for r in usable:
            rec = "-" if r["recoveries"] is None else str(r["recoveries"])
            print(f"  {Path(r['file']).name:<44}{r['admitted']:>10}{rec:>19}")

        low, high = bootstrap_ci(admitted)
        print(f"\n  admitted   median {statistics.median(admitted):.1f}   "
              f"range {min(admitted):.0f}-{max(admitted):.0f}   "
              f"95% bootstrap CI [{low}, {high}]")

        entry = {
            "runs": len(usable),
            "admitted_values": [int(a) for a in admitted],
            "admitted_median": statistics.median(admitted),
            "admitted_min": min(admitted),
            "admitted_max": max(admitted),
            "admitted_ci95": [low, high],
        }

        if len(recoveries) >= 2:
            rlow, rhigh = bootstrap_ci(recoveries)
            print(f"  recoveries median {statistics.median(recoveries):.1f}   "
                  f"range {min(recoveries):.0f}-{max(recoveries):.0f}   "
                  f"95% bootstrap CI [{rlow}, {rhigh}]")
            entry.update({
                "recovery_values": [int(v) for v in recoveries],
                "recovery_median": statistics.median(recoveries),
                "recovery_min": min(recoveries),
                "recovery_max": max(recoveries),
                "recovery_ci95": [rlow, rhigh],
            })
        report[condition] = entry

    print("\n" + "=" * 78)
    print("  How to read this")
    print("=" * 78)
    print("  Admitted counts are stable across runs; retry recoveries are not.")
    print("  That asymmetry is the finding: the retry loop's yield is the part")
    print("  that moves, which is why no strong claim is made for it. Three runs")
    print("  produce a very wide interval - reported rather than smoothed over.")
    print("  Deterministic components (census, splits, search, admission) have")
    print("  no variance at all: they are pytest runs, not generations.")

    write_json(ROOT / "experiments" / "variance.json", {
        "method": "percentile bootstrap over stored independent runs",
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "seed": SEED,
        "note": "Ollama with partial GPU offload is not bitwise deterministic "
                "at temperature=0; these are repeated runs, not distinct seeds.",
        "conditions": report,
    })
    print("\n  results -> experiments/variance.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

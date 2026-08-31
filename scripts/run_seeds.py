"""Repeat the headline conditions to put error bars on the main comparison.

The gap this closes
-------------------
`experiments/variance.json` measures spread for one condition only, so the
headline comparison - direct-prompt baseline versus the best scaffolded
condition - has been reported as two single runs. Two single runs cannot
distinguish a real effect from generation noise.

This repeats both headline conditions and reports median, range and a
percentile bootstrap interval for each, plus a paired per-fault comparison so
the two are compared on the same faults rather than in aggregate.

Ollama with partial GPU offload is not bitwise deterministic even at
temperature 0, so "seeds" here means independent repeated runs under nominally
identical settings. That is the honest description of what is collected.

Results are written after **every** run, so a partial sweep is still usable.

Usage:
  python scripts/run_seeds.py --repeats 3 --conditions baseline_A placebo_D
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from placebo.agents.llm import LocalModel, ModelConfig  # noqa: E402
from placebo.agents.test_author import TestAuthor  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402
from run_experiment import CONDITIONS, select_working_set  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]
OUT = ROOT / "experiments" / "seeds.json"
BOOTSTRAP = 10_000


def bootstrap_ci(values: list[float], confidence: float = 0.95) -> list[float]:
    """Percentile bootstrap interval over the observed runs."""
    if len(values) < 2:
        return [values[0], values[0]] if values else [0.0, 0.0]
    rng = random.Random(1729)
    means = sorted(
        sum(rng.choice(values) for _ in values) / len(values)
        for _ in range(BOOTSTRAP)
    )
    lo = means[int((1 - confidence) / 2 * len(means))]
    hi = means[int((1 + confidence) / 2 * len(means)) - 1]
    return [round(lo, 3), round(hi, 3)]


def summarise(values: list[float]) -> dict:
    return {
        "runs": len(values),
        "values": [int(v) for v in values],
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "ci95": bootstrap_ci(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--conditions", nargs="+",
                        default=["baseline_A", "placebo_D"])
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--model", default="qwen2.5:7b")
    args = parser.parse_args()

    subject = ROOT / "subject"
    census = json.loads((ROOT / "artifacts" / "census.json").read_text(encoding="utf-8"))
    by_id = {m.id: m for m in enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)}
    working_set = select_working_set(census, by_id, args.limit)

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "seeds", timeout_s=60)
    runner.prepare()

    print("=" * 78)
    print(f"  REPEATED RUNS  ({args.repeats} per condition, "
          f"{len(working_set)} faults each)")
    print("  Same settings every run; Ollama is not bitwise deterministic.")
    print("=" * 78)

    # Per-fault admission across runs, so the conditions can be compared paired.
    per_fault: dict[str, dict[str, list[bool]]] = {}
    admitted_by_condition: dict[str, list[float]] = {}
    started = time.perf_counter()

    for condition in args.conditions:
        config = CONDITIONS[condition]
        admitted_by_condition.setdefault(condition, [])
        per_fault.setdefault(condition, {})

        for run_index in range(1, args.repeats + 1):
            model = LocalModel(
                ModelConfig(model=args.model),
                trajectory=ROOT / "trajectories" / f"seeds_{condition}.jsonl",
            )
            if not model.available():
                print(f"  model {args.model} unavailable; stopping")
                return 1
            author = TestAuthor(model, runner, subject / "semver" / "version.py")

            run_started = time.perf_counter()
            admitted = 0
            for mutant in working_set:
                outcome = author.author(mutant, config)
                per_fault[condition].setdefault(mutant.id, []).append(outcome.admitted)
                admitted += 1 if outcome.admitted else 0

            admitted_by_condition[condition].append(float(admitted))
            print(f"  {condition:<14} run {run_index}/{args.repeats}: "
                  f"admitted {admitted}/{len(working_set)}   "
                  f"({time.perf_counter() - run_started:.0f}s, "
                  f"{model.usage()['calls']} calls)", flush=True)

            # Persist after every run so a partial sweep is still usable.
            payload = {
                "method": "independent repeated runs; not distinct RNG seeds",
                "repeats_requested": args.repeats,
                "faults_per_run": len(working_set),
                "model": args.model,
                "bootstrap_samples": BOOTSTRAP,
                "conditions": {
                    name: summarise(values)
                    for name, values in admitted_by_condition.items() if values
                },
                "per_fault_admission": per_fault,
                "wall_s": round(time.perf_counter() - started, 1),
            }
            write_json(OUT, payload)

    print("\n" + "=" * 78)
    print(f"  {'condition':<16}{'runs':>6}{'median':>9}{'range':>12}{'95% CI':>16}")
    print("  " + "-" * 74)
    for name, values in admitted_by_condition.items():
        if not values:
            continue
        s = summarise(values)
        span = f"{s['min']:.0f}-{s['max']:.0f}"
        print(f"  {name:<16}{s['runs']:>6}{s['median']:>9.1f}"
              f"{span:>12}{str(s['ci95']):>16}")
    print("=" * 78)
    print(f"  results -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

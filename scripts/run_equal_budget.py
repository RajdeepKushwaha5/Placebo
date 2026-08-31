"""Equal-budget resampling baseline.

The objection this answers
-------------------------
Placebo's best condition spends more model calls than the direct-prompt
baseline. A reasonable judge asks: did the scaffolding help, or did it just buy
more attempts? Recent work suggests plain resampling at equal budget can rival
feedback-driven loops, so this has to be measured rather than argued.

Method
------
Give the *direct prompt* the same call budget the scaffolded condition used, as
independent samples rather than a feedback loop:

    for each fault:
        draw N independent candidates from the plain prompt
        keep the first that passes on clean HEAD   <- what a developer keeps
        also record whether any of them detects the fault

The baseline is scored the way a developer would use it (keep what is green),
and additionally credited for its best-of-N detection, which is the *generous*
reading. If Placebo still wins under the generous reading, extra attempts were
not the explanation.

Writes experiments/equal_budget.json. Touches no existing artifact.

Usage:
  python scripts/run_equal_budget.py --samples 3 --limit 12
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from placebo.agents.llm import LocalModel, ModelConfig  # noqa: E402
from placebo.agents.test_author import AuthorConfig, TestAuthor  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402
from placebo.verification.admission import admit  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402
from run_experiment import select_working_set  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]
CANDIDATE = "tests/test_equal_budget.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--model", default="qwen2.5:7b")
    args = parser.parse_args()

    subject = ROOT / "subject"
    census = json.loads((ROOT / "artifacts" / "census.json").read_text(encoding="utf-8"))
    by_id = {m.id: m for m in enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)}
    working_set = select_working_set(census, by_id, args.limit)

    model = LocalModel(
        ModelConfig(model=args.model),
        trajectory=ROOT / "trajectories" / "equal_budget.jsonl",
    )
    if not model.available():
        print(f"model {args.model} unavailable")
        return 1

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "equalbudget", timeout_s=60)
    runner.prepare()
    author = TestAuthor(model, runner, subject / "semver" / "version.py")

    # Condition A prompt (no fault shown), drawn N times independently.
    config = AuthorConfig("equal_budget_A", condition="A", max_attempts=1)

    print("=" * 78)
    print(f"  EQUAL-BUDGET RESAMPLING BASELINE  ({args.samples} independent draws)")
    print("  same prompt as baseline_A, same budget as the scaffolded conditions")
    print("=" * 78)

    started = time.perf_counter()
    results = []
    green_any = detect_any = 0

    for index, mutant in enumerate(working_set, 1):
        samples, kept_green, detected = [], None, False
        for draw in range(args.samples):
            outcome = author.author(mutant, config)
            code = outcome.attempts[0].code if outcome.attempts else ""
            if not code.strip():
                samples.append({"draw": draw + 1, "status": "NO_CODE"})
                continue

            report = admit(runner, mutant, code, CANDIDATE, repeats=1)
            passed_clean = "clean_head" in report.gates_passed
            samples.append({
                "draw": draw + 1,
                "verdict": report.code.value if report.code else "ADMITTED",
                "green_on_clean": passed_clean,
                "detects_fault": report.admitted,
            })
            if passed_clean and kept_green is None:
                kept_green = code           # what a developer would keep
            if report.admitted:
                detected = True

        if kept_green is not None:
            green_any += 1
        if detected:
            detect_any += 1

        print(f"  [{index:>2}/{len(working_set)}] "
              f"green={'yes' if kept_green else ' no'}  "
              f"best-of-{args.samples} detects={'yes' if detected else ' no'}  "
              f"{mutant.operator.value}", flush=True)

        results.append({
            "mutant_id": mutant.id,
            "kept_a_green_candidate": kept_green is not None,
            "any_draw_detects_fault": detected,
            "samples": samples,
        })

    wall = time.perf_counter() - started
    usage = model.usage()
    total = len(working_set)

    print("\n" + "=" * 78)
    print(f"  faults attempted                    : {total}")
    print(f"  kept a green candidate (developer)  : {green_any}/{total}")
    print(f"  best-of-{args.samples} detects the fault (generous): {detect_any}/{total}")
    print(f"  model calls                         : {usage['calls']}")
    print(f"  wall                                : {wall:.0f}s")
    print("=" * 78)
    print("  Compare against placebo_D: 7/12 admitted using 23 calls. If this")
    print("  baseline does not reach that under the generous best-of-N reading,")
    print("  extra attempts were not what made the difference.")

    write_json(ROOT / "experiments" / "equal_budget.json", {
        "method": "independent resampling of the direct prompt at matched budget",
        "samples_per_fault": args.samples,
        "faults": total,
        "kept_green_candidate": green_any,
        "best_of_n_detects": detect_any,
        "model_calls": usage["calls"],
        "output_tokens": usage["output_tokens"],
        "model_seconds": usage["model_seconds"],
        "usd_cost": usage["usd_cost"],
        "wall_s": round(wall, 1),
        "comparison_note": "placebo_D admitted 7/12 using 23 model calls",
        "results": results,
    })
    print("\n  results -> experiments/equal_budget.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

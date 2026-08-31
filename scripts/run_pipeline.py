"""Placebo end-to-end pipeline.

  1. enumerate mutants in the target module
  2. load the census (which faults the expert human suite catches)
  3. select a stratified DISCOVERY working set
  4. freeze a HELD-OUT split (same functions, different spans, never revealed)
  5. run each condition's agent over the discovery mutants
  6. assemble each condition's admitted tests into a suite
  7. apply the same model-free green-test repair to every suite (fairness)
  8. score every suite on the frozen held-out mutants
  9. emit the comparison table

Usage:
  python scripts/run_pipeline.py --conditions baseline_A placebo_B placebo_C
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.agents.llm import LocalModel, ModelConfig  # noqa: E402
from placebo.agents.test_author import TestAuthor  # noqa: E402
from placebo.evaluation.evaluator import (  # noqa: E402
    assemble_suite,
    evaluate_suite,
)
from placebo.evaluation.repair import count_tests, keep_green_tests  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402
from placebo.mutation.split import build_split  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from run_experiment import CONDITIONS, select_working_set  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conditions", nargs="+",
                        default=["baseline_A", "mutant_aware_B1", "placebo_B", "placebo_C"])
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--held-per-function", type=int, default=3)
    parser.add_argument("--model", default="qwen2.5:7b")
    args = parser.parse_args()

    subject = ROOT / "subject"
    source_file = subject / "semver" / "version.py"
    full_source = source_file.read_text(encoding="utf-8")

    # ---- 1-2. mutants + census ------------------------------------------
    all_mutants = enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)
    by_id = {m.id: m for m in all_mutants}
    census = json.loads((ROOT / "artifacts" / "census.json").read_text(encoding="utf-8"))
    killable = {mid for mid, r in census.items() if r["status"] == "killed"}

    # ---- 3. discovery working set ---------------------------------------
    discovery = select_working_set(census, by_id, args.limit)

    # ---- 4. frozen held-out split ---------------------------------------
    split = build_split(discovery, all_mutants, killable,
                        per_function=args.held_per_function)
    split.assert_disjoint()
    write_json(ROOT / "benchmark" / "manifests" / "split.json", split.to_manifest())

    print("=" * 72)
    print("  PLACEBO PIPELINE")
    print("=" * 72)
    print(f"  subject          : semver @ {SUBJECT_COMMIT[:12]}  ({TARGET_FILES[0]})")
    print(f"  mutants total    : {len(all_mutants)}")
    print(f"  discovery set    : {len(split.discovery)}")
    print(f"  held-out set     : {len(split.held_out)}  (frozen, fingerprint "
          f"{split.fingerprint})")
    print(f"  held-out families: {dict(Counter(m.operator.value for m in split.held_out))}")
    print(f"  model            : {args.model}")
    print("=" * 72)

    # 60 s, not the 300 s census default. A single candidate test should take
    # under a second; an unconstrained generated test that loops would otherwise
    # burn five minutes per case and dominate wall time.
    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "pipeline", timeout_s=60)
    runner.prepare()

    scores, condition_meta = [], {}

    for cond_name in args.conditions:
        config = CONDITIONS[cond_name]
        model = LocalModel(
            ModelConfig(model=args.model),
            trajectory=ROOT / "trajectories" / f"pipeline_{cond_name}.jsonl",
        )
        if not model.available():
            print(f"model {args.model} unavailable on {model.config.host}")
            return 1
        author = TestAuthor(model, runner, source_file)

        print(f"\n--- {cond_name}  (context={config.condition}, "
              f"max_attempts={config.max_attempts}) ---")
        started = time.perf_counter()
        admitted: list[tuple] = []
        results = []
        for n, mutant in enumerate(split.discovery, 1):
            res = author.author(mutant, config)
            results.append(res)
            if res.admitted:
                admitted.append((mutant, res.admitted_code))
            print(f"  [{n:>2}/{len(split.discovery)}] "
                  f"{'ADMIT' if res.admitted else 'reject':6s} "
                  f"attempts={res.attempts_used}  {mutant.operator.value}", flush=True)
        gen_wall = time.perf_counter() - started

        # ---- 6-7. assemble + fair repair --------------------------------
        raw_suite = assemble_suite(admitted, full_source) if admitted else ""
        repaired, kept, dropped = (
            keep_green_tests(runner, raw_suite) if raw_suite else ("", [], [])
        )

        # ---- 8. held-out scoring ----------------------------------------
        print(f"  scoring {count_tests(repaired)} tests on "
              f"{len(split.held_out)} held-out mutants ...", flush=True)
        score = evaluate_suite(
            runner, cond_name, repaired, split.held_out, count_tests(repaired)
        )
        scores.append(score)

        suite_dir = ROOT / "artifacts" / "suites"
        suite_dir.mkdir(parents=True, exist_ok=True)
        (suite_dir / f"{cond_name}.py").write_text(repaired or "# no admitted tests\n",
                                                   encoding="utf-8")

        condition_meta[cond_name] = {
            "context_condition": config.condition,
            "max_attempts": config.max_attempts,
            "discovery_admitted": len(admitted),
            "discovery_total": len(split.discovery),
            "tests_after_repair": count_tests(repaired),
            "repair_dropped": dropped,
            "generation_wall_s": round(gen_wall, 1),
            "usage": model.usage(),
            "score": score.to_dict(),
        }
        write_json(ROOT / "experiments" / "raw" / f"pipeline_{cond_name}.json",
                   {"meta": condition_meta[cond_name],
                    "results": [r.to_dict() for r in results]})

        print(f"  discovery admitted : {len(admitted)}/{len(split.discovery)}")
        print(f"  held-out killed    : {len(score.killed)}/{score.scorable} "
              f"({score.mutation_score:.1%})")
        print(f"  coverage           : line {score.line_coverage}%  "
              f"branch {score.branch_coverage}%")

    # ---- 9. comparison table --------------------------------------------
    print("\n" + "=" * 78)
    print("  HELD-OUT COMPARISON  (mutants frozen before generation, never shown)")
    print("=" * 78)
    print(f"  {'condition':<18}{'tests':>6}{'held-out kill':>15}"
          f"{'line cov':>10}{'branch cov':>12}{'model s':>10}")
    print("  " + "-" * 74)
    for s in scores:
        usage = condition_meta[s.name]["usage"]
        print(f"  {s.name:<18}{s.tests:>6}"
              f"{f'{len(s.killed)}/{s.scorable} ({s.mutation_score:.0%})':>15}"
              f"{s.line_coverage:>9.1f}%{s.branch_coverage:>11.1f}%"
              f"{usage['model_seconds']:>10.0f}")
    print("=" * 78)

    write_json(ROOT / "experiments" / "results.json", {
        "subject_commit": SUBJECT_COMMIT,
        "target_files": TARGET_FILES,
        "model": args.model,
        "split_fingerprint": split.fingerprint,
        "discovery_count": len(split.discovery),
        "held_out_count": len(split.held_out),
        "conditions": condition_meta,
    })
    print(f"\n  results -> experiments/results.json")
    print(f"  suites  -> artifacts/suites/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run one or more experimental conditions over a fixed mutant working set.

Every condition sees the SAME mutants, the same model, the same seed and the
same admission gates, so differences are attributable to scaffolding alone.

Usage:
  python scripts/run_experiment.py --conditions baseline_A placebo_B
  python scripts/run_experiment.py --conditions placebo_B --limit 7
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
from placebo.agents.test_author import AuthorConfig, TestAuthor  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]

# The experimental conditions. `baseline_*` are the fair comparators.
CONDITIONS: dict[str, AuthorConfig] = {
    # What a developer gets today: one direct prompt, no fault shown, no loop.
    "baseline_A": AuthorConfig("baseline_A", condition="A", max_attempts=1),
    # Isolates "better context": the agent is shown the proven fault.
    "mutant_aware_B1": AuthorConfig("mutant_aware_B1", condition="B", max_attempts=1),
    # Isolates "verification": same context, plus the structured retry loop.
    "placebo_B": AuthorConfig("placebo_B", condition="B", max_attempts=3),
    # Isolates "contract grounding": body withheld from the author.
    "placebo_C": AuthorConfig("placebo_C", condition="C", max_attempts=3),
    # Isolates "oracle grounding": the model picks inputs, execution supplies
    # the expected values. Targets the measured dominant failure mode.
    "placebo_D": AuthorConfig("placebo_D", condition="D", max_attempts=3),
}


def select_working_set(census: dict, mutants: dict, limit: int) -> list:
    """Deterministic, stratified working set.

    Mutants the expert human suite already kills stand in for the gaps an
    AI-generated suite typically leaves. Selection is round-robin across
    operator families so no single family dominates the result.
    """
    pool = [mutants[mid] for mid, r in sorted(census.items())
            if r["status"] == "killed" and mid in mutants]
    families: dict[str, list] = {}
    for m in pool:
        families.setdefault(m.operator.value, []).append(m)
    for fam in families.values():
        fam.sort(key=lambda m: m.id)

    picked, i = [], 0
    order = sorted(families)
    while len(picked) < limit and any(len(families[f]) > i for f in order):
        for fam in order:
            if len(families[fam]) > i and len(picked) < limit:
                picked.append(families[fam][i])
        i += 1
    return picked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conditions", nargs="+", default=["placebo_B"])
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()

    subject = ROOT / "subject"
    census = json.loads((ROOT / "artifacts" / "census.json").read_text(encoding="utf-8"))
    mutants = {m.id: m for m in enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)}
    working_set = select_working_set(census, mutants, args.limit)

    print(f"working set: {len(working_set)} mutants")
    for fam, n in Counter(m.operator.value for m in working_set).most_common():
        print(f"  {fam:22s} {n}")
    write_json(
        ROOT / "benchmark" / "manifests" / "working_set.json",
        [m.to_dict() for m in working_set],
    )

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "exp", timeout_s=60)
    runner.prepare()

    all_results: dict[str, list] = {}
    for cond_name in args.conditions:
        config = CONDITIONS[cond_name]
        tag = args.tag or time.strftime("%Y%m%d-%H%M%S")
        model = LocalModel(
            ModelConfig(model=args.model),
            trajectory=ROOT / "trajectories" / f"{cond_name}.jsonl",
        )
        if not model.available():
            print(f"model {args.model} unavailable")
            return 1

        author = TestAuthor(model, runner, subject / "semver" / "version.py")
        print(f"\n{'='*70}\nCONDITION {cond_name}  "
              f"(context={config.condition}, max_attempts={config.max_attempts})\n{'='*70}")

        results, started = [], time.perf_counter()
        for n, mutant in enumerate(working_set, 1):
            res = author.author(mutant, config)
            results.append(res)
            codes = [a.report.code.value if a.report.code else "OK" for a in res.attempts]
            flag = "ADMIT" if res.admitted else "reject"
            print(f"  [{n:>2}/{len(working_set)}] {flag:6s} "
                  f"attempts={res.attempts_used} {'->'.join(codes):<48} "
                  f"{mutant.operator.value}", flush=True)

        wall = time.perf_counter() - started
        admitted = sum(1 for r in results if r.admitted)
        first_try = sum(1 for r in results if r.admitted and r.attempts_used == 1)
        rejection_counter: Counter[str] = Counter()
        for r in results:
            for a in r.attempts:
                if a.report.code:
                    rejection_counter[a.report.code.value] += 1

        summary = {
            "condition": cond_name,
            "context_condition": config.condition,
            "max_attempts": config.max_attempts,
            "model": args.model,
            "model_digest": model.digest(),
            "working_set_size": len(working_set),
            "admitted": admitted,
            "admission_rate": round(admitted / len(working_set), 4),
            "admitted_first_attempt": first_try,
            "rejections": dict(rejection_counter),
            "wall_s": round(wall, 1),
            "usage": model.usage(),
        }
        write_json(ROOT / "experiments" / "raw" / f"{cond_name}_{tag}.json",
                   {"summary": summary, "results": [r.to_dict() for r in results]})
        write_json(ROOT / "experiments" / "raw" / f"{cond_name}_summary.json", summary)
        all_results[cond_name] = results

        print(f"\n  admitted        : {admitted}/{len(working_set)} "
              f"({admitted/len(working_set):.0%})")
        print(f"  first attempt   : {first_try}")
        print(f"  rejection codes : {dict(rejection_counter)}")
        print(f"  wall            : {wall:.0f}s   usage: {model.usage()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

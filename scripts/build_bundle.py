"""Assemble the evidence bundle for one condition.

Runs from stored results only — no model calls — so the deliverable a reviewer
receives can be rebuilt and audited for free.

Usage:
  python scripts/build_bundle.py --condition placebo_D
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.agents.llm import LocalModel, ModelConfig  # noqa: E402
from placebo.evaluation.repair import split_tests  # noqa: E402
from placebo.evidence.bundle import (  # noqa: E402
    build_bundle,
    environment_record,
    evidence_for,
)
from placebo.mutation.engine import enumerate_subject  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", default="")
    parser.add_argument("--out", default="artifacts/bundle")
    parser.add_argument(
        "--real-gaps", action="store_true",
        help="bundle the end-to-end confirmed-gap patch instead of a benchmark condition",
    )
    args = parser.parse_args()

    results_path = ROOT / "experiments" / "results.json"
    if not results_path.exists():
        print("experiments/results.json not found - run scripts/rescore.py first")
        return 1
    results = json.loads(results_path.read_text(encoding="utf-8"))
    conditions = results["conditions"]

    # Default to the best-scoring condition that used the oracle.
    condition = args.condition
    if args.real_gaps:
        condition = "real_gap_closure"
        gap = json.loads(
            (ROOT / "experiments" / "real_gap_closure.json").read_text(encoding="utf-8")
        )
        meta = {
            "score": {
                "evaluation": "confirmed repository gaps",
                "clean_passes": gap["union_clean_passes"],
                "mutation_score": gap["gap_closure_rate"],
                "killed": gap["killed"],
                "survived": gap["survived"],
                "scorable": gap["confirmed_gaps"],
            }
        }
        suite_path = ROOT / "artifacts" / "suites" / "real_gap_patch.py"
        raw = gap
    elif not condition:
        eligible = {
            k: v for k, v in conditions.items()
            if v.get("suite_policy") == "oracle-admitted only"
        } or conditions
        condition = max(
            eligible, key=lambda k: eligible[k]["score"]["mutation_score"]
        )
    if not args.real_gaps:
        meta = conditions[condition]
        suite_path = ROOT / "artifacts" / "suites" / f"{condition}.py"
        raw_path = ROOT / "experiments" / "raw" / f"pipeline_{condition}.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    print(f"building bundle for condition: {condition}")

    suite = suite_path.read_text(encoding="utf-8")

    subject = ROOT / "subject"
    full_source = (subject / "semver" / "version.py").read_text(encoding="utf-8")
    mutants = {m.id: m for m in enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)}

    # Recover which fault each test in the assembled suite detects, from the
    # `# mutant id:` annotation written at assembly time.
    _, tests = split_tests(suite)
    annotations = dict(
        re.findall(r"# mutant id: (\w+)\n\s*(?:#.*\n\s*)*def (test_\w+)", suite)
    )
    name_to_mutant = {name: mid for mid, name in annotations.items()}

    gates_by_mutant = {
        r["mutant_id"]: (r["attempts"][-1]["admission"].get("gates_passed", [])
                         if r.get("attempts") else [])
        for r in raw.get("results", [])
    }

    evidences = []
    for name, _src in tests:
        mid = name_to_mutant.get(name)
        mutant = mutants.get(mid) if mid else None
        if mutant is None:
            print(f"  warning: no recorded fault for {name}; skipping evidence")
            continue
        evidences.append(
            evidence_for(mutant, name, full_source, gates_by_mutant.get(mid, []))
        )

    model = LocalModel(ModelConfig(model=results.get("model", "qwen2.5:7b")))
    env = environment_record(model.config.model, model.digest())

    evaluation_score = dict(meta["score"])
    if not args.real_gaps and meta.get("score_stratified"):
        evaluation_score = dict(meta["score_stratified"])
        evaluation_score["evaluation"] = "pre-generation frozen confirmatory set"
        evaluation_score["robustness_all_eligible"] = meta["score"]

    out = build_bundle(
        ROOT / args.out,
        suite_code=suite,
        evidences=evidences,
        heldout_score=evaluation_score,
        environment=env,
        subject_commit=SUBJECT_COMMIT,
    )

    print(f"  tests with evidence : {len(evidences)}")
    print(f"  evaluation score    : {evaluation_score['mutation_score']:.1%}")
    print(f"  bundle              : {out.relative_to(ROOT)}")
    print(f"\n  verify with: python scripts/verify_bundle.py --bundle {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

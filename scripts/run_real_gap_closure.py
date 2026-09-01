"""Close confirmed gaps in the subject's real 100%-coverage test suite.

The benchmark pipeline uses known-detectable faults to compare authoring
strategies on a sufficiently large paired set. This script is the product demo:
it starts from faults that actually survived semver's existing 329-test suite,
asks the oracle-grounded agent for focused tests, and measures the union of the
existing suite plus the generated patch against those confirmed gaps.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.agents.llm import LocalModel, ModelConfig  # noqa: E402
from placebo.agents.test_author import AuthorConfig, TestAuthor  # noqa: E402
from placebo.evaluation.evaluator import SUITE_PATH, assemble_suite  # noqa: E402
from placebo.evaluation.repair import count_tests, keep_green_tests  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import MutantStatus, write_json  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]


def main() -> int:
    subject = ROOT / "subject"
    source_file = subject / TARGET_FILES[0]
    source = source_file.read_text(encoding="utf-8")
    mutants = {
        m.id: m for m in enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)
    }
    triage = json.loads(
        (ROOT / "artifacts" / "survivor_triage.json").read_text(encoding="utf-8")
    )
    gap_ids = [
        item["id"] for item in triage["findings"]
        if item["verdict"] == "CONFIRMED_REAL_GAP"
    ]
    gaps = [mutants[mid] for mid in gap_ids]

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "real-gaps", timeout_s=60)
    runner.prepare()
    baseline = runner.check_baseline()
    if not baseline.passed:
        print("subject baseline is not green; refusing to generate evidence")
        return 2

    model = LocalModel(
        ModelConfig(model="qwen2.5:7b"),
        trajectory=ROOT / "trajectories" / "real_gap_closure.jsonl",
    )
    if not model.available():
        print("qwen2.5:7b is not available from Ollama")
        return 1
    author = TestAuthor(model, runner, source_file)
    config = AuthorConfig("real_gap_closure", condition="D", max_attempts=3)

    print("=" * 74)
    print("  REAL GAP CLOSURE: semver expert suite + Placebo patch")
    print(f"  confirmed gaps: {len(gaps)}")
    print("=" * 74)
    started = time.perf_counter()
    results = []
    admitted = []
    for index, mutant in enumerate(gaps, 1):
        result = author.author(mutant, config)
        results.append(result)
        if result.admitted:
            admitted.append((mutant, result.admitted_code))
        print(
            f"  [{index}/{len(gaps)}] "
            f"{'ADMIT' if result.admitted else 'reject':6s} "
            f"attempts={result.attempts_used}  {mutant.label}",
            flush=True,
        )

    raw_suite = assemble_suite(admitted, source, fault_claim=True) if admitted else ""
    suite, kept, dropped = (
        keep_green_tests(runner, raw_suite) if raw_suite else ("", [], [])
    )
    suite_path = ROOT / "artifacts" / "suites" / "real_gap_patch.py"
    suite_path.parent.mkdir(parents=True, exist_ok=True)
    suite_path.write_text(suite or "# no admitted tests\n", encoding="utf-8")

    with runner.extra_tests({SUITE_PATH: suite} if suite else {}):
        union_clean = runner.run_suite()

    killed, survived, invalid = [], [], []
    for mutant in gaps:
        run = runner.run_mutant(
            mutant,
            extra={SUITE_PATH: suite} if suite else None,
        )
        if run.status is MutantStatus.KILLED:
            killed.append(mutant.id)
        elif run.status is MutantStatus.SURVIVED:
            survived.append(mutant.id)
        else:
            invalid.append(mutant.id)

    payload = {
        "subject_commit": SUBJECT_COMMIT,
        "existing_tests": 329,
        "confirmed_gaps": len(gaps),
        "candidate_tests_admitted": len(admitted),
        "tests_after_repair": count_tests(suite),
        "repair_dropped": dropped,
        "union_clean_passes": union_clean.passed,
        "gaps_closed": len(killed),
        "gap_closure_rate": round(len(killed) / len(gaps), 4) if gaps else 0.0,
        "killed": killed,
        "survived": survived,
        "invalid": invalid,
        "usage": model.usage(),
        "wall_s": round(time.perf_counter() - started, 1),
        "results": [result.to_dict() for result in results],
    }
    write_json(ROOT / "experiments" / "real_gap_closure.json", payload)

    report = [
        "# Placebo: real gap closure\n",
        f"- Existing expert suite: **329 tests, 100% line and branch coverage**",
        f"- Confirmed detectable gaps before Placebo: **{len(gaps)}**",
        f"- Generated tests retained: **{count_tests(suite)}**",
        f"- Existing suite + patch remains green: **{union_clean.passed}**",
        f"- Confirmed gaps closed: **{len(killed)}/{len(gaps)} "
        f"({payload['gap_closure_rate']:.0%})**",
        f"- Model calls: **{payload['usage']['calls']}**; monetary cost: **$0**\n",
        "This is the end-to-end product result. Unlike the authoring benchmark, "
        "every fault here actually survived the repository's existing suite and "
        "was separately confirmed to be behaviorally detectable.",
    ]
    (ROOT / "artifacts" / "real_gap_report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )

    print("=" * 74)
    print(f"  union clean : {union_clean.passed}")
    print(f"  gaps closed: {len(killed)}/{len(gaps)} ({payload['gap_closure_rate']:.0%})")
    print(f"  patch      : {suite_path.relative_to(ROOT)}")
    print("=" * 74)
    return 0 if union_clean.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())

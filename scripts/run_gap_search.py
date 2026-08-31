"""Close the remaining real gaps with deterministic counterexample search.

The measured bottleneck after oracle grounding was input search: of the six
confirmed gaps in semver's own suite, Placebo closed three and failed the other
three because the agent could not find inputs that separate correct code from
the fault.

This runs the deterministic search on **all six** confirmed gaps and reports
closure. It makes no model calls at all, so any improvement is attributable to
the search and not to a luckier generation.

Usage:
  python scripts/run_gap_search.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.evaluation.evaluator import SUITE_PATH  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import MutantStatus, write_json  # noqa: E402
from placebo.search.counterexample import (  # noqa: E402
    search_counterexample,
    synthesize_from_witness,
)
from placebo.verification.admission import admit  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]
CANDIDATE = "tests/test_placebo_search.py"


def main() -> int:
    subject = ROOT / "subject"
    triage = json.loads(
        (ROOT / "artifacts" / "survivor_triage.json").read_text(encoding="utf-8")
    )
    confirmed = [
        f["id"] for f in triage["findings"]
        if f["verdict"] == "CONFIRMED_REAL_GAP"
    ]
    mutants = {m.id: m for m in enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)}

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "search", timeout_s=60)
    runner.prepare()

    print("=" * 78)
    print("  DETERMINISTIC COUNTEREXAMPLE SEARCH on confirmed real gaps")
    print(f"  {len(confirmed)} gaps that survived semver's own 329-test suite")
    print("  model calls: 0")
    print("=" * 78)

    results, admitted_tests = [], []
    started = time.perf_counter()

    for index, gap_id in enumerate(sorted(confirmed), 1):
        mutant = mutants[gap_id]
        print(f"\n[{index}/{len(confirmed)}] {mutant.label}")

        search = search_counterexample(runner, mutant)
        if not search.found:
            print(f"    tried {search.candidates_tried} candidates - no witness found")
            results.append({"mutant_id": gap_id, "closed": False,
                            "search": search.to_dict()})
            continue

        witness = search.witness
        print(f"    tried {search.candidates_tried} candidates, "
              f"{len(search.all_distinguishing)} distinguish")
        print(f"    minimal witness : {witness.expr}")
        print(f"      clean  -> {witness.clean_repr[:60]}")
        print(f"      faulty -> {witness.mutant_repr[:60]}")

        code = synthesize_from_witness(mutant, search, "test_placebo_search")
        report = admit(runner, mutant, code, CANDIDATE, repeats=2)
        print(f"    admission       : "
              f"{'ADMITTED' if report.admitted else report.code.value}")

        if report.admitted:
            admitted_tests.append((mutant, code))
        results.append({
            "mutant_id": gap_id,
            "closed": report.admitted,
            "witness": witness.expr,
            "clean": witness.clean_repr,
            "faulty": witness.mutant_repr,
            "search": search.to_dict(),
            "admission": report.to_dict(),
        })

    wall = time.perf_counter() - started
    closed = sum(1 for r in results if r["closed"])

    # ---- union check: existing suite + generated patch stays green -------
    union_green = None
    if admitted_tests:
        from placebo.evaluation.evaluator import assemble_suite
        full_source = (subject / "semver" / "version.py").read_text(encoding="utf-8")
        suite = assemble_suite(admitted_tests, full_source)
        out = ROOT / "artifacts" / "suites" / "search_gap_patch.py"
        out.write_text(suite, encoding="utf-8")

        with runner.extra_tests({SUITE_PATH: suite}):
            union = runner.run_suite()
        union_green = union.passed
        print(f"\n  existing 329-test suite + patch green: {union_green}")

        # Confirm each gap is actually closed by the union, not just alone.
        still_open = []
        for mutant, _code in admitted_tests:
            with runner.extra_tests({SUITE_PATH: suite}):
                run = runner.run_mutant(mutant, extra={SUITE_PATH: suite})
            if run.status is not MutantStatus.KILLED:
                still_open.append(mutant.id)
        print(f"  gaps closed when run with the full suite: "
              f"{len(admitted_tests) - len(still_open)}/{len(admitted_tests)}")

    print("\n" + "=" * 78)
    print(f"  gaps closed by search : {closed}/{len(confirmed)}")
    print(f"  wall time             : {wall:.0f}s")
    print(f"  model calls           : 0    cost: $0.00")
    print("=" * 78)

    write_json(ROOT / "experiments" / "gap_search.json", {
        "confirmed_gaps": len(confirmed),
        "gaps_closed": closed,
        "closure_rate": round(closed / len(confirmed), 4) if confirmed else 0.0,
        "model_calls": 0,
        "usd_cost": 0.0,
        "wall_s": round(wall, 1),
        "union_clean_passes": union_green,
        "results": results,
    })
    print("\n  results -> experiments/gap_search.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

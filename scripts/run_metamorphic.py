"""Evaluate metamorphic properties as a level-3 oracle.

Placebo's default oracle is a *snapshot*: run the input, record what came back.
That cannot separate "correct" from "what this code currently does". Metamorphic
properties assert relationships between executions instead, so they hardcode no
expected value and cannot inherit a pre-existing bug from the reference.

Two questions are asked:

1. Do the properties hold on clean code? If not, the property is wrong and any
   detection it reports is meaningless.
2. How many confirmed gaps do they detect, with no snapshot values and no model
   calls?

Usage:
  python scripts/run_metamorphic.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402
from placebo.search.metamorphic import (  # noqa: E402
    PROPERTIES,
    check_properties,
    synthesize_property_test,
)
from placebo.verification.admission import admit  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]
CANDIDATE = "tests/test_placebo_metamorphic.py"


def main() -> int:
    subject = ROOT / "subject"
    triage = json.loads(
        (ROOT / "artifacts" / "survivor_triage.json").read_text(encoding="utf-8")
    )
    confirmed = sorted(
        f["id"] for f in triage["findings"] if f["verdict"] == "CONFIRMED_REAL_GAP"
    )
    mutants = {m.id: m for m in enumerate_subject(subject, TARGET_FILES, SUBJECT_COMMIT)}

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "metamorphic", timeout_s=90)
    runner.prepare()

    print("=" * 78)
    print("  METAMORPHIC PROPERTIES  (level-3 oracle: no hardcoded outputs)")
    print(f"  {len(PROPERTIES)} properties evaluated on {len(confirmed)} confirmed gaps")
    print("  model calls: 0")
    print("=" * 78)

    started = time.perf_counter()
    results, detected, admitted_count = [], 0, 0
    unsound_names: set[str] = set()

    for index, gap_id in enumerate(confirmed, 1):
        mutant = mutants[gap_id]
        print(f"\n[{index}/{len(confirmed)}] {mutant.label}")

        checks = check_properties(runner, mutant)
        unsound = [c for c in checks if not c.holds_on_clean]
        detectors = [c for c in checks if c.detects]
        unsound_names.update(c.name for c in unsound)

        if unsound:
            print(f"    WARNING: {len(unsound)} property(ies) do not hold on clean "
                  f"code: {sorted(c.name for c in unsound)}")

        if not detectors:
            print("    no property distinguishes this fault")
            results.append({"mutant_id": gap_id, "detected": False,
                            "properties": [c.to_dict() for c in checks]})
            continue

        detected += 1
        print(f"    detected by {len(detectors)} property(ies): "
              f"{', '.join(c.name for c in detectors[:3])}")
        print(f"    example: {detectors[0].example[:68]}")

        code = synthesize_property_test(mutant, checks, "test_placebo_metamorphic")
        report = admit(runner, mutant, code, CANDIDATE, repeats=2)
        if report.admitted:
            admitted_count += 1
        print(f"    admission: {'ADMITTED' if report.admitted else report.code.value}")

        results.append({
            "mutant_id": gap_id,
            "detected": True,
            "detecting_properties": [c.name for c in detectors],
            "example": detectors[0].example,
            "admitted": report.admitted,
            "properties": [c.to_dict() for c in checks],
        })

    wall = time.perf_counter() - started

    print("\n" + "=" * 78)
    print(f"  properties sound on clean code : "
          f"{'yes' if not unsound_names else 'NO - ' + str(sorted(unsound_names))}")
    print(f"  confirmed gaps detected        : {detected}/{len(confirmed)}")
    print(f"  synthesized tests admitted     : {admitted_count}/{detected}")
    print(f"  model calls: 0    wall: {wall:.0f}s")
    print("=" * 78)
    print("  These assertions record no output values, so unlike a snapshot")
    print("  witness they cannot encode an existing bug as expected behavior.")

    write_json(ROOT / "experiments" / "metamorphic.json", {
        "properties_defined": len(PROPERTIES),
        "confirmed_gaps": len(confirmed),
        "gaps_detected": detected,
        "tests_admitted": admitted_count,
        "all_properties_sound_on_clean": not unsound_names,
        "unsound_properties": sorted(unsound_names),
        "model_calls": 0,
        "wall_s": round(wall, 1),
        "results": results,
    })
    print("\n  results -> experiments/metamorphic.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

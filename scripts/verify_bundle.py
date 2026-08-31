"""Independently re-verify a Placebo evidence bundle.

Takes nothing on trust. For every test in the bundle it re-applies the exact
fault that test claims to detect and re-runs the test, checking both directions:

    HOLDS   test passes on clean HEAD AND fails with the fault injected
    BROKEN  either direction no longer holds

Exits non-zero if any claim is broken, so it can gate CI.

Usage:
  python scripts/verify_bundle.py --bundle artifacts/bundle
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.evaluation.repair import split_tests  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

PROBE = "tests/test_bundle_verify.py"
TARGET_FILES = ["semver/version.py"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", default="artifacts/bundle")
    args = parser.parse_args()

    bundle = ROOT / args.bundle
    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists():
        print(f"no bundle at {bundle}")
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tests_evidence = json.loads(
        (bundle / "evidence" / "tests.json").read_text(encoding="utf-8")
    )
    suite = (bundle / manifest["patch_path"]).read_text(encoding="utf-8")

    subject = ROOT / "subject"
    mutants = {
        m.id: m
        for m in enumerate_subject(subject, TARGET_FILES, manifest["subject_commit"])
    }
    preamble, tests = split_tests(suite)
    by_name = dict(tests)

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "verify", timeout_s=60)
    runner.prepare()

    print("=" * 74)
    print(f"  VERIFYING BUNDLE  {bundle.name}")
    print(f"  subject {manifest['subject_commit'][:12]}   tests {len(tests_evidence)}")
    print("=" * 74)

    broken = 0
    for entry in tests_evidence:
        name = entry["test_name"]
        fault = entry["detects_fault"]
        mutant = mutants.get(fault["mutant_id"])
        source = by_name.get(name)

        if mutant is None or source is None:
            print(f"  BROKEN  {name}: fault or test not found in bundle")
            broken += 1
            continue

        probe = preamble + "\n" + source

        with runner.extra_tests({PROBE: probe}):
            clean = runner.run_suite([PROBE])
        if not clean.passed:
            print(f"  BROKEN  {name}: no longer passes on clean HEAD")
            broken += 1
            continue

        run = runner.run_mutant(mutant, selection=[PROBE], extra={PROBE: probe})
        if run.status.value != "killed":
            print(f"  BROKEN  {name}: no longer detects {fault['mutant_id']} "
                  f"({run.status.value})")
            broken += 1
            continue

        print(f"  HOLDS   {name}  detects {fault['mutant_id']}  "
              f"{fault['label'][:52]}")

    print("=" * 74)
    total = len(tests_evidence)
    print(f"  {total - broken}/{total} claims hold")
    if broken:
        print(f"  {broken} BROKEN")
    print("=" * 74)
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())

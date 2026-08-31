"""Triage the survivors of the subject's own expert suite.

A survivor is only interesting if it represents a fault a test *could* catch.
Mutants that no test can distinguish -- equivalent mutants -- must be excluded
from any honest mutation score.

Rather than eyeball them, this script pairs each survivor with a hand-written
test and runs it through the same oracle Placebo uses. If the test passes on
clean HEAD and fails on the mutant, the survivor is a CONFIRMED REAL GAP. If no
such test can be written, it is reported as equivalent-or-contract-only.

These tests are written by a human (the author), not by the agent, and are used
only for triage -- never as part of any condition's suite.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.mutation.models import write_json  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
PROBE = "tests/test_triage_probe.py"

# One hand-written killing test per survivor, with the reasoning for it.
TRIAGE: dict[str, dict] = {
    "33797d243637a3c5": {
        "why": "`'...%s' % type` becomes `'...%s' * type`. Both raise TypeError, "
               "so a bare pytest.raises(TypeError) cannot tell them apart — but "
               "the message differs, so asserting it does.",
        "test": '''
import pytest, semver

def test_triage():
    with pytest.raises(TypeError) as excinfo:
        semver.Version.parse(3.14)
    assert "not expecting type" in str(excinfo.value)
''',
    },
    "400588ba9c9f77f9": {
        "why": "self[:4] -> self[:5] pulls build metadata into the 0.x "
               "compatibility check. Semver says build metadata is ignored.",
        "test": '''
import semver

def test_triage():
    a = semver.Version.parse("0.1.0+build.1")
    b = semver.Version.parse("0.1.0+build.2")
    assert a.is_compatible(b) is True
''',
    },
    "a6eb2ad4fd7271ea": {
        "why": "Same line, other[:4] -> other[:5]; same build-metadata leak.",
        "test": '''
import semver

def test_triage():
    a = semver.Version.parse("0.1.0+build.1")
    b = semver.Version.parse("0.1.0+build.2")
    assert a.is_compatible(b) is True
''',
    },
    "52d0f2279f7370b9": {
        "why": "EQUIVALENT — the mutated line is in DEAD CODE. In semver 3.0.4, "
               "`bump_build` computes `build`, increments it, then recomputes "
               "the identical if/elif chain and increments again, discarding "
               "the first result entirely. The mutant sits in that discarded "
               "first block, so no input can distinguish it. Mutation testing "
               "surfaced an upstream redundancy that 100% coverage did not. "
               "(The expected value below, '1.2.3+1', was obtained from the "
               "oracle rather than guessed — the author's first hand-written "
               "guess of '1.2.3+0' was wrong, which is precisely the failure "
               "mode Placebo removes from the agent.)",
        "test": '''
import semver

def test_triage():
    assert str(semver.Version.parse("1.2.3").bump_build(token="")) == "1.2.3+1"
    assert str(semver.Version.parse("1.2.3").bump_build(token="x")) == "1.2.3+x.1"
''',
    },
    "7c644c64bde4883c": {
        "why": '">=": (0, 1) -> (1, 1) drops equality, so ">=x" stops matching x.',
        "test": '''
import semver

def test_triage():
    assert semver.Version.parse("1.0.0").match(">=1.0.0") is True
''',
    },
    "bad59b17cefa1f72": {
        "why": '"<=": (-1, 0) -> (-1, 1) makes "<=x" match versions greater than x.',
        "test": '''
import semver

def test_triage():
    assert semver.Version.parse("2.0.0").match("<=1.0.0") is False
''',
    },
    "95f32034b4f97f3d": {
        "why": "`return False` -> `return None`. None is falsy, so every "
               "truthiness use is unaffected. Only an identity/equality "
               "assertion on the return value can see it.",
        "test": '''
import semver

def test_triage():
    a = semver.Version.parse("0.1.0")
    b = semver.Version.parse("0.2.0")
    assert a.is_compatible(b) is False
''',
    },
}


def main() -> int:
    subject = ROOT / "subject"
    census = json.loads((ROOT / "artifacts" / "census.json").read_text(encoding="utf-8"))
    mutants = {m.id: m for m in enumerate_subject(subject, ["semver/version.py"], SUBJECT_COMMIT)}
    survivors = [mid for mid, r in census.items() if r["status"] == "survived"]

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "triage", timeout_s=60)
    runner.prepare()

    findings = []
    print(f"Triaging {len(survivors)} survivors of the expert suite\n" + "=" * 72)
    for mid in sorted(survivors):
        mutant = mutants[mid]
        entry = TRIAGE.get(mid)
        print(f"\n{mid}  {mutant.label}")
        if not entry:
            print("  no triage test written")
            findings.append({"id": mid, "verdict": "UNTRIAGED", "label": mutant.label})
            continue
        print(f"  reasoning: {entry['why']}")

        code = entry["test"].strip() + "\n"
        with runner.extra_tests({PROBE: code}):
            clean = runner.run_suite([PROBE])
        if not clean.passed:
            print("  triage test does not pass on clean HEAD -> inconclusive")
            findings.append({"id": mid, "verdict": "INCONCLUSIVE", "label": mutant.label,
                             "why": entry["why"]})
            continue

        run = runner.run_mutant(mutant, selection=[PROBE], extra={PROBE: code})
        if run.status.value == "killed":
            print("  VERDICT: CONFIRMED REAL GAP (a test can catch it; the "
                  "expert suite has none)")
            verdict = "CONFIRMED_REAL_GAP"
        else:
            print(f"  VERDICT: EQUIVALENT_OR_CONTRACT_ONLY ({run.status.value})")
            verdict = "EQUIVALENT_OR_CONTRACT_ONLY"
        findings.append({"id": mid, "verdict": verdict, "label": mutant.label,
                         "why": entry["why"], "killing_test": code})

    confirmed = sum(1 for f in findings if f["verdict"] == "CONFIRMED_REAL_GAP")
    scorable = census and len([1 for r in census.values()
                               if r["status"] in ("killed", "survived")])
    killed = len([1 for r in census.values() if r["status"] == "killed"])

    print("\n" + "=" * 72)
    print(f"  confirmed real gaps          : {confirmed}/{len(survivors)}")
    print(f"  equivalent / contract-only   : {len(survivors) - confirmed}")
    print(f"  reported mutation score      : {killed/scorable:.1%} "
          f"({killed}/{scorable})")
    adjusted_denom = scorable - (len(survivors) - confirmed)
    print(f"  equivalence-adjusted score   : {killed/adjusted_denom:.1%} "
          f"({killed}/{adjusted_denom})")
    print("=" * 72)

    write_json(ROOT / "artifacts" / "survivor_triage.json", {
        "survivors": len(survivors),
        "confirmed_real_gaps": confirmed,
        "equivalent_or_contract_only": len(survivors) - confirmed,
        "reported_mutation_score": round(killed / scorable, 4),
        "equivalence_adjusted_score": round(killed / adjusted_denom, 4),
        "findings": findings,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

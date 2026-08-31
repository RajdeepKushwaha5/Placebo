"""Marginal fault-detection value: auditing tests instead of counting them.

The reframe
-----------
A test that kills mutants can still be worthless. If every fault it detects is
already detected by another test, it adds no protection — only review burden and
runtime. Test value is therefore not absolute but **counterfactual**:

    value(t) = faults detectable with t  -  faults detectable without t

This module computes that directly, per test, against two reference points:

* the **repository's existing suite** — does this test detect anything the repo
  could not already detect? A test that only re-detects covered faults is
  redundant with the code that was already there.
* its **sibling tests in the same patch** — among the new tests, is this one the
  only one that detects a given fault?

Efficiency
----------
The naive matrix costs |tests| x |faults| test-suite launches. It is not
needed: pytest reports *which* tests failed, so injecting one fault and running
the whole suite once yields an entire column of the kill matrix. The number of
launches is |faults| rather than |tests| x |faults|; total runtime still depends
on the size and speed of the suite.

Honesty
-------
"Detects nothing" is not a claim this module makes. It reports that a test
showed **no marginal fault sensitivity under the evaluated fault models**, which
is what was actually measured. A test may still encode a requirement no mutant
in the corpus expresses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from ..evaluation.repair import split_tests
from ..mutation.models import Mutant
from ..verification.runner import SubjectRunner

AUDIT_PATH = "tests/test_placebo_audit.py"

# pytest reports node ids as "path::test_name"; we want the function name.
_NODE_ID = re.compile(r"::([A-Za-z_]\w*)")


class Verdict(str, Enum):
    """Classification of one test's demonstrated marginal value."""

    VALUABLE = "VALUABLE"
    #   Detects at least one fault that neither the existing suite nor any
    #   sibling test in this patch detects. Unique, novel protection.

    REDUNDANT_WITH_SIBLING = "REDUNDANT_WITH_SIBLING"
    #   Detects faults the existing suite misses, but a sibling test in the same
    #   patch detects them too. Reviewable, but the patch could be smaller.

    REDUNDANT_WITH_EXISTING = "REDUNDANT_WITH_EXISTING"
    #   Only re-detects faults the repository's own suite already detects. Adds
    #   review burden and runtime without adding protection.

    UNPROVEN = "UNPROVEN"
    #   No marginal fault sensitivity under the evaluated fault models. NOT a
    #   claim that the test is useless.

    HARMFUL = "HARMFUL"
    #   Red against correct code, unstable across runs, or otherwise unfit to
    #   merge regardless of what it detects.


@dataclass
class TestAudit:
    """The measured record for one test in the audited suite."""

    name: str
    green_on_clean: bool
    stable: bool
    detects: list[str] = field(default_factory=list)
    novel: list[str] = field(default_factory=list)
    unique_novel: list[str] = field(default_factory=list)
    verdict: Verdict = Verdict.UNPROVEN
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "test": self.name,
            "verdict": self.verdict.value,
            "green_on_clean": self.green_on_clean,
            "stable": self.stable,
            "faults_detected": len(self.detects),
            "faults_missed_by_existing_suite": len(self.novel),
            "uniquely_detected": len(self.unique_novel),
            "unique_fault_ids": sorted(self.unique_novel),
            "note": self.note,
        }


@dataclass
class SuiteAudit:
    """Audit of a whole candidate patch."""

    suite_name: str
    tests: list[TestAudit] = field(default_factory=list)
    fault_corpus: int = 0
    existing_suite_gaps: int = 0

    def by_verdict(self, verdict: Verdict) -> list[TestAudit]:
        return [t for t in self.tests if t.verdict is verdict]

    @property
    def retained(self) -> list[TestAudit]:
        """The minimal patch: tests carrying unique, novel protection."""
        return self.by_verdict(Verdict.VALUABLE)

    @property
    def removable(self) -> list[TestAudit]:
        return [
            t for t in self.tests
            if t.verdict in (Verdict.REDUNDANT_WITH_SIBLING,
                             Verdict.REDUNDANT_WITH_EXISTING,
                             Verdict.UNPROVEN)
        ]

    def summary(self) -> dict:
        counts = {v.value: len(self.by_verdict(v)) for v in Verdict}
        covered = {f for t in self.tests for f in t.novel}
        return {
            "suite": self.suite_name,
            "tests_audited": len(self.tests),
            "fault_corpus": self.fault_corpus,
            "existing_suite_gaps_in_corpus": self.existing_suite_gaps,
            "verdicts": counts,
            "gaps_closed_by_patch": len(covered),
            "review_burden_reduction": (
                round(len(self.removable) / len(self.tests), 4) if self.tests else 0.0
            ),
        }


def sample_fault_corpus(
    faults: list[Mutant], existing_kills: set[str], limit: int
) -> list[Mutant]:
    """Reduce the fault corpus without silently dropping the interesting faults.

    Naive truncation (``faults[:limit]``) is actively misleading. Enumeration
    order is by source position, so a small limit can exclude every fault the
    repository's suite misses — and a patch that closes real gaps would then be
    reported as detecting nothing novel. That is not a slower answer; it is the
    opposite answer.

    Every fault the existing suite does *not* detect is therefore always kept,
    and the remainder is filled deterministically with covered faults so the
    redundancy signal stays meaningful.
    """
    if limit <= 0 or limit >= len(faults):
        return faults

    gaps = [f for f in faults if f.id not in existing_kills]
    covered = [f for f in faults if f.id in existing_kills]

    keep = list(gaps[:limit])
    # Even spread across the covered faults rather than the first N, so the
    # sample is not biased toward one end of the file.
    remaining = limit - len(keep)
    if remaining > 0 and covered:
        step = max(1, len(covered) // remaining)
        keep.extend(covered[::step][:remaining])

    order = {f.id: i for i, f in enumerate(faults)}
    return sorted(keep, key=lambda f: order[f.id])


def _failing_test_names(failing: list[str]) -> set[str]:
    """Extract bare test function names from pytest node ids."""
    names: set[str] = set()
    for entry in failing:
        match = _NODE_ID.search(entry)
        if match:
            names.add(match.group(1))
    return names


def audit_suite(
    runner: SubjectRunner,
    suite_name: str,
    suite_code: str,
    faults: list[Mutant],
    existing_kills: set[str],
    stability_repeats: int = 2,
) -> SuiteAudit:
    """Compute per-test marginal fault-detection value.

    `existing_kills` is the set of fault ids the repository's own suite already
    detects, taken from the census. Faults outside that set are the repo's real
    blind spots, and detecting one of those is what "novel" means here.
    """
    audit = SuiteAudit(suite_name=suite_name, fault_corpus=len(faults))
    audit.existing_suite_gaps = sum(1 for f in faults if f.id not in existing_kills)

    preamble, tests = split_tests(suite_code)
    if not tests:
        return audit

    records: dict[str, TestAudit] = {}

    # ---- fitness: green and stable against correct code ------------------
    for name, source in tests:
        probe = preamble + "\n" + source
        verdicts = []
        for _ in range(max(1, stability_repeats)):
            with runner.extra_tests({AUDIT_PATH: probe}):
                verdicts.append(runner.run_suite([AUDIT_PATH]).passed)
        green = verdicts[0]
        stable = len(set(verdicts)) == 1
        records[name] = TestAudit(name=name, green_on_clean=green, stable=stable)
        if not green:
            records[name].verdict = Verdict.HARMFUL
            records[name].note = "fails against correct code"
        elif not stable:
            records[name].verdict = Verdict.HARMFUL
            records[name].note = "not deterministic across repeat runs"

    # Only mergeable tests can be credited with detecting anything.
    eligible = {n for n, r in records.items() if r.green_on_clean and r.stable}
    if not eligible:
        audit.tests = list(records.values())
        return audit

    # ---- kill matrix: one execution per fault ----------------------------
    for fault in faults:
        run = runner.run_mutant(
            fault, selection=[AUDIT_PATH], extra={AUDIT_PATH: suite_code}
        )
        if run.status.value not in ("killed", "survived"):
            continue  # invalid/timeout faults are not scoreable evidence
        detected_by = _failing_test_names(run.failing_tests) & eligible
        for name in detected_by:
            records[name].detects.append(fault.id)
            if fault.id not in existing_kills:
                records[name].novel.append(fault.id)

    # ---- counterfactual: which novel faults has exactly one detector? ----
    novel_detectors: dict[str, list[str]] = {}
    for name in eligible:
        for fault_id in records[name].novel:
            novel_detectors.setdefault(fault_id, []).append(name)
    for fault_id, detectors in novel_detectors.items():
        if len(detectors) == 1:
            records[detectors[0]].unique_novel.append(fault_id)

    # ---- classify ---------------------------------------------------------
    for name in eligible:
        record = records[name]
        if record.unique_novel:
            record.verdict = Verdict.VALUABLE
            record.note = (
                f"sole detector of {len(record.unique_novel)} fault(s) the "
                "existing suite misses"
            )
        elif record.novel:
            record.verdict = Verdict.REDUNDANT_WITH_SIBLING
            record.note = (
                "detects gaps in the existing suite, but a sibling test in this "
                "patch detects the same ones"
            )
        elif record.detects:
            record.verdict = Verdict.REDUNDANT_WITH_EXISTING
            record.note = (
                f"only re-detects {len(record.detects)} fault(s) the existing "
                "suite already catches"
            )
        else:
            record.verdict = Verdict.UNPROVEN
            record.note = (
                "no marginal fault sensitivity under the evaluated fault models"
            )

    audit.tests = [records[n] for n, _ in tests]
    return audit


def select_minimal_cover(audit: SuiteAudit) -> tuple[list[str], set[str]]:
    """Smallest test set preserving every novel fault the patch detects.

    Keeping only VALUABLE tests is **wrong**, and the bug is worth naming
    because it is easy to ship: a fault detected by three sibling tests makes
    all three "redundant with a sibling", so dropping every redundant test
    drops that fault entirely. Minimization is a set-cover problem over the
    novel faults, not a per-test filter.

    Greedy cover is used. It does not guarantee the theoretical optimum, but it
    does guarantee the property that actually matters here — the returned set
    detects exactly the same novel faults as the full patch — and that property
    is asserted before returning, then re-verified by execution in the audit
    script.
    """
    eligible = [
        t for t in audit.tests
        if t.verdict is not Verdict.HARMFUL and t.novel
    ]
    target: set[str] = {f for t in eligible for f in t.novel}

    chosen: list[str] = []
    covered: set[str] = set()
    remaining = list(eligible)

    while covered != target and remaining:
        # Most new faults first; ties broken by name for determinism.
        remaining.sort(
            key=lambda t: (-len(set(t.novel) - covered), t.name)
        )
        best = remaining.pop(0)
        gain = set(best.novel) - covered
        if not gain:
            break
        chosen.append(best.name)
        covered |= gain

    if covered != target:  # pragma: no cover - defensive
        raise AssertionError(
            f"minimization would lose faults: {sorted(target - covered)}"
        )
    return chosen, target


def minimal_patch(audit: SuiteAudit, suite_code: str) -> tuple[str, list[str], set[str]]:
    """Return (minimized_suite, kept_test_names, novel_faults_preserved)."""
    keep, preserved = select_minimal_cover(audit)
    preamble, tests = split_tests(suite_code)
    kept = [src for name, src in tests if name in keep]
    if not kept:
        return ("", [], preserved)
    return (preamble + "\n" + "\n\n".join(kept), keep, preserved)

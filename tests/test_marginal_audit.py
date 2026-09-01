"""Tests for the marginal-value audit.

`audit_suite` is the function that turns executions into verdicts, and it was
the least covered load-bearing code in the project: the set-cover minimizer had
tests, but the classification that feeds it did not. That matters more than
usual here, because the audit path is about to be optimised with caching and
test selection, and the exit criterion for that work is "never lose a kill".
A safety net that only covers the minimizer would not notice a lost kill.

The runner is faked. Real execution is covered end to end by
`scripts/run_audit.py` in CI; what these tests pin is the logic that decides
what an execution *means*, which is where a wrong answer would be silent.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.audit.marginal import (  # noqa: E402
    AUDIT_PATH,
    SuiteAudit,
    Verdict,
    audit_suite,
    minimal_patch,
    sample_fault_corpus,
    select_minimal_cover,
)
from placebo.audit.marginal import TestAudit as AuditRecord  # noqa: E402
from placebo.mutation.models import (  # noqa: E402
    Mutant,
    MutantRun,
    MutantStatus,
    OperatorFamily,
)
from placebo.verification.runner import RunResult  # noqa: E402

COMMIT = "0" * 40


def fault(tag: str) -> Mutant:
    """A distinct fault whose content-derived id is stable across runs."""
    return Mutant(
        file="pkg/m.py",
        qualname=f"f_{tag}",
        operator=OperatorFamily.COMPARISON_BOUNDARY,
        lineno=1,
        col=0,
        span_start=0,
        span_end=1,
        original="<",
        replacement="<=",
        subject_commit=COMMIT,
    )


class FakeRunner:
    """A repository whose behaviour is declared rather than executed.

    `kills` maps a fault id to the test names that fail when it is injected.
    `red` names tests that fail against correct code, and `flaky` names tests
    whose clean result alternates, which is how instability is expressed.
    """

    def __init__(self, kills=None, red=(), flaky=(), invalid=()):
        self.kills = kills or {}
        self.red = set(red)
        self.flaky = set(flaky)
        self.invalid = set(invalid)
        self._staged = ""
        self._clean_calls: dict[str, int] = {}
        self.mutant_runs = 0

    @contextmanager
    def extra_tests(self, files: dict[str, str]):
        self._staged = files[AUDIT_PATH]
        try:
            yield
        finally:
            self._staged = ""

    def _staged_name(self) -> str:
        for line in self._staged.splitlines():
            if line.startswith("def test_"):
                return line[4:].split("(")[0]
        return ""

    def run_suite(self, selection=None, tb="no") -> RunResult:
        name = self._staged_name()
        seen = self._clean_calls.get(name, 0)
        self._clean_calls[name] = seen + 1
        # A flaky test passes on the first probe and fails on the next, so the
        # two stability repeats disagree.
        failed = name in self.red or (name in self.flaky and seen > 0)
        return RunResult(
            returncode=1 if failed else 0,
            duration_s=0.0,
            stdout="",
            stderr="",
            failing_tests=[f"{AUDIT_PATH}::{name}"] if failed else [],
        )

    def run_mutant(self, mutant, selection=None, extra=None) -> MutantRun:
        self.mutant_runs += 1
        if mutant.id in self.invalid:
            return MutantRun(mutant_id=mutant.id, status=MutantStatus.INVALID,
                             duration_s=0.0)
        killers = self.kills.get(mutant.id, [])
        return MutantRun(
            mutant_id=mutant.id,
            status=MutantStatus.KILLED if killers else MutantStatus.SURVIVED,
            duration_s=0.0,
            failing_tests=[f"{AUDIT_PATH}::{n}" for n in killers],
        )


def suite(*names: str) -> str:
    body = "\n\n".join(f"def {n}():\n    assert True" for n in names)
    return "import pytest\n\n\n" + body + "\n"


# -- verdicts --------------------------------------------------------------


def test_sole_detector_of_a_gap_is_valuable():
    gap = fault("gap")
    runner = FakeRunner(kills={gap.id: ["test_a"]})
    audit = audit_suite(runner, "s", suite("test_a", "test_b"), [gap], existing_kills=set())

    a = next(t for t in audit.tests if t.name == "test_a")
    assert a.verdict is Verdict.VALUABLE
    assert a.unique_novel == [gap.id]
    assert next(t for t in audit.tests if t.name == "test_b").verdict is Verdict.UNPROVEN


def test_two_detectors_of_one_gap_are_redundant_with_each_other():
    """Neither is the sole detector, so neither is VALUABLE. This is exactly
    the shape that made the old minimizer drop the fault entirely."""
    gap = fault("gap")
    runner = FakeRunner(kills={gap.id: ["test_a", "test_b"]})
    audit = audit_suite(runner, "s", suite("test_a", "test_b"), [gap], existing_kills=set())

    assert {t.verdict for t in audit.tests} == {Verdict.REDUNDANT_WITH_SIBLING}
    kept, preserved = select_minimal_cover(audit)
    assert len(kept) == 1, "one of the two suffices"
    assert preserved == {gap.id}, "but the fault must survive minimization"


def test_redetecting_what_the_repo_already_catches_is_redundant():
    covered = fault("covered")
    runner = FakeRunner(kills={covered.id: ["test_a"]})
    audit = audit_suite(runner, "s", suite("test_a"), [covered],
                        existing_kills={covered.id})

    a = audit.tests[0]
    assert a.verdict is Verdict.REDUNDANT_WITH_EXISTING
    assert a.detects == [covered.id]
    assert a.novel == [], "already covered, so nothing novel"


def test_test_that_is_red_on_clean_code_is_harmful_and_gets_no_credit():
    """A red test must not be credited even when it does detect the fault."""
    gap = fault("gap")
    runner = FakeRunner(kills={gap.id: ["test_bad"]}, red=["test_bad"])
    audit = audit_suite(runner, "s", suite("test_bad"), [gap], existing_kills=set())

    bad = audit.tests[0]
    assert bad.verdict is Verdict.HARMFUL
    assert not bad.green_on_clean
    assert bad.detects == [], "an unmergeable test cannot be credited"


def test_unstable_test_is_harmful():
    gap = fault("gap")
    runner = FakeRunner(kills={gap.id: ["test_flaky"]}, flaky=["test_flaky"])
    audit = audit_suite(runner, "s", suite("test_flaky"), [gap], existing_kills=set())

    rec = audit.tests[0]
    assert rec.verdict is Verdict.HARMFUL
    assert not rec.stable
    assert "deterministic" in rec.note


def test_invalid_faults_are_not_scored():
    """A mutant that does not import is not evidence either way."""
    broken = fault("broken")
    runner = FakeRunner(kills={broken.id: ["test_a"]}, invalid={broken.id})
    audit = audit_suite(runner, "s", suite("test_a"), [broken], existing_kills=set())

    assert audit.tests[0].detects == []
    assert audit.tests[0].verdict is Verdict.UNPROVEN


def test_empty_patch_returns_an_empty_audit():
    audit = audit_suite(FakeRunner(), "s", "import pytest\n", [fault("x")], set())
    assert audit.tests == []
    assert audit.summary()["tests_audited"] == 0


def test_all_tests_red_short_circuits_before_the_fault_matrix():
    """No eligible test means the kill matrix cannot change any verdict, so
    running it would be wasted work."""
    runner = FakeRunner(red=["test_a"])
    audit = audit_suite(runner, "s", suite("test_a"), [fault("x")], set())

    assert runner.mutant_runs == 0, "no execution should be spent"
    assert audit.tests[0].verdict is Verdict.HARMFUL


def test_one_execution_per_fault_regardless_of_test_count():
    """The column trick: pytest names which tests failed, so a whole column of
    the kill matrix costs one run."""
    faults = [fault(f"f{i}") for i in range(5)]
    runner = FakeRunner(kills={f.id: ["test_a"] for f in faults})
    audit_suite(runner, "s", suite("test_a", "test_b", "test_c"), faults, set())

    assert runner.mutant_runs == 5


# -- reporting -------------------------------------------------------------


def test_summary_accounts_for_every_test_exactly_once():
    gap, covered = fault("gap"), fault("covered")
    runner = FakeRunner(kills={gap.id: ["test_a"], covered.id: ["test_b"]},
                        red=["test_c"])
    audit = audit_suite(runner, "s", suite("test_a", "test_b", "test_c"),
                        [gap, covered], existing_kills={covered.id})

    summary = audit.summary()
    assert sum(summary["verdicts"].values()) == summary["tests_audited"] == 3
    assert summary["gaps_closed_by_patch"] == 1
    assert summary["existing_suite_gaps_in_corpus"] == 1


def test_review_burden_counts_every_test_the_patch_does_not_need():
    """The metric was once computed against retained VALUABLE tests only, which
    understated it by excluding HARMFUL tests from what a reviewer can drop."""
    gap = fault("gap")
    runner = FakeRunner(kills={gap.id: ["test_a"]}, red=["test_b", "test_c"])
    audit = audit_suite(runner, "s", suite("test_a", "test_b", "test_c"),
                        [gap], existing_kills=set())

    # One test carries the patch; the other two are unmergeable.
    assert audit.summary()["review_burden_reduction"] == round(2 / 3, 4)


def test_audit_records_serialise():
    gap = fault("gap")
    runner = FakeRunner(kills={gap.id: ["test_a"]})
    audit = audit_suite(runner, "s", suite("test_a"), [gap], existing_kills=set())

    payload = audit.tests[0].to_dict()
    assert payload["verdict"] == "VALUABLE"
    assert payload["uniquely_detected"] == 1
    assert payload["unique_fault_ids"] == [gap.id]


def test_retained_and_removable_partition_the_non_harmful_tests():
    audit = SuiteAudit(suite_name="s")
    audit.tests = [
        AuditRecord("a", True, True, verdict=Verdict.VALUABLE),
        AuditRecord("b", True, True, verdict=Verdict.REDUNDANT_WITH_EXISTING),
        AuditRecord("c", True, True, verdict=Verdict.UNPROVEN),
        AuditRecord("d", False, True, verdict=Verdict.HARMFUL),
    ]
    assert [t.name for t in audit.retained] == ["a"]
    assert sorted(t.name for t in audit.removable) == ["b", "c"]


# -- minimization ----------------------------------------------------------


def test_minimal_patch_is_valid_python_and_keeps_the_chosen_tests():
    import ast

    gap = fault("gap")
    code = suite("test_a", "test_b")
    runner = FakeRunner(kills={gap.id: ["test_a"]})
    audit = audit_suite(runner, "s", code, [gap], existing_kills=set())

    minimized, kept, preserved = minimal_patch(audit, code)
    ast.parse(minimized)
    assert kept == ["test_a"]
    assert preserved == {gap.id}
    assert "def test_b" not in minimized


def test_minimal_patch_of_a_patch_with_nothing_novel_is_empty():
    covered = fault("covered")
    code = suite("test_a")
    runner = FakeRunner(kills={covered.id: ["test_a"]})
    audit = audit_suite(runner, "s", code, [covered], existing_kills={covered.id})

    minimized, kept, _ = minimal_patch(audit, code)
    assert minimized == "" and kept == []


def test_harmful_tests_are_never_selected_by_the_cover():
    gap = fault("gap")
    runner = FakeRunner(kills={gap.id: ["test_red"]}, red=["test_red"])
    audit = audit_suite(runner, "s", suite("test_red"), [gap], existing_kills=set())

    kept, preserved = select_minimal_cover(audit)
    assert kept == [] and preserved == set()


# -- fault sampling --------------------------------------------------------


def test_sampling_never_drops_a_gap():
    """Naive truncation gave the opposite answer, reporting a gap-closing patch
    as detecting nothing."""
    covered = [fault(f"c{i}") for i in range(50)]
    gaps = [fault(f"g{i}") for i in range(3)]
    kills = {f.id for f in covered}

    sampled = sample_fault_corpus(covered + gaps, kills, limit=10)
    assert len(sampled) == 10
    assert {f.id for f in gaps} <= {f.id for f in sampled}


def test_sampling_is_deterministic_and_order_preserving():
    faults = [fault(f"f{i}") for i in range(30)]
    kills = {f.id for f in faults[:25]}
    order = {f.id: i for i, f in enumerate(faults)}

    first = sample_fault_corpus(faults, kills, limit=8)
    assert [f.id for f in first] == [f.id for f in sample_fault_corpus(faults, kills, 8)]
    positions = [order[f.id] for f in first]
    assert positions == sorted(positions), "sample must keep enumeration order"


def test_sampling_is_a_noop_when_the_limit_does_not_bind():
    faults = [fault(f"f{i}") for i in range(5)]
    assert sample_fault_corpus(faults, set(), limit=0) is faults
    assert sample_fault_corpus(faults, set(), limit=99) is faults


# -- progress reporting ----------------------------------------------------


def test_progress_is_reported_for_both_phases_and_counts_up_to_the_total():
    """The audit was once silent until completion. The stream is what tells a
    user it is working rather than hung, so the counters must be truthful."""
    faults = [fault(f"f{i}") for i in range(3)]
    runner = FakeRunner(kills={faults[0].id: ["test_a"]})
    seen: list[tuple[str, int, int]] = []

    audit_suite(runner, "s", suite("test_a", "test_b"), faults,
                existing_kills=set(), stability_repeats=2,
                progress=lambda phase, done, total: seen.append((phase, done, total)))

    phases = {p for p, _, _ in seen}
    assert phases == {"clean/stability checks", "fault matrix"}

    clean = [(d, t) for p, d, t in seen if p == "clean/stability checks"]
    # 2 tests x 2 repeats, counting 1..4 with a constant total.
    assert clean == [(1, 4), (2, 4), (3, 4), (4, 4)]

    matrix = [(d, t) for p, d, t in seen if p == "fault matrix"]
    assert matrix == [(1, 3), (2, 3), (3, 3)]


def test_audit_runs_without_a_progress_callback():
    """Progress is optional; passing nothing must not crash the audit."""
    gap = fault("gap")
    audit = audit_suite(FakeRunner(kills={gap.id: ["test_a"]}), "s",
                        suite("test_a"), [gap], existing_kills=set())
    assert audit.tests[0].verdict is Verdict.VALUABLE

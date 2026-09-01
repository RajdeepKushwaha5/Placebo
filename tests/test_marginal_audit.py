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
        self.last_selection: list[str] | None = None
        self.tests_executed = 0

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
        self.last_selection = list(selection) if selection else None

        # Mirror pytest: a node-id selection runs only those tests, so only
        # those can be reported as failing. Selecting the file runs them all.
        ran = self._selected_names(selection, extra)
        self.tests_executed += len(ran)

        if mutant.id in self.invalid:
            return MutantRun(mutant_id=mutant.id, status=MutantStatus.INVALID,
                             duration_s=0.0)
        killers = [n for n in self.kills.get(mutant.id, []) if n in ran]
        return MutantRun(
            mutant_id=mutant.id,
            status=MutantStatus.KILLED if killers else MutantStatus.SURVIVED,
            duration_s=0.0,
            failing_tests=[f"{AUDIT_PATH}::{n}" for n in killers],
        )

    @staticmethod
    def _selected_names(selection, extra) -> set[str]:
        code = (extra or {}).get(AUDIT_PATH, "")
        in_file = {
            line[4:].split("(")[0]
            for line in code.splitlines() if line.startswith("def test_")
        }
        if not selection or selection == [AUDIT_PATH]:
            return in_file
        return {s.split("::")[-1] for s in selection} & in_file


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


# -- caching ---------------------------------------------------------------


def test_progress_counts_invalid_faults_too():
    """The counter previously skipped unscoreable faults, so the displayed
    total could never be reached and the run looked stuck near the end."""
    faults = [fault("ok"), fault("broken")]
    runner = FakeRunner(kills={faults[0].id: ["test_a"]}, invalid={faults[1].id})
    seen: list[tuple[int, int]] = []

    audit_suite(runner, "s", suite("test_a"), faults, set(),
                progress=lambda p, d, t: seen.append((d, t)) if p == "fault matrix" else None)

    assert seen == [(1, 2), (2, 2)]


def test_a_cached_rerun_executes_nothing_and_agrees_exactly(tmp_path):
    """The speed claim. A second audit of the same patch must reuse every
    recorded execution, and must reach the same verdicts by doing so."""
    from placebo.cache import ResultCache

    gap, covered = fault("gap"), fault("covered")
    code = suite("test_a", "test_b")
    kills = {gap.id: ["test_a"], covered.id: ["test_b"]}

    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        cold_runner = FakeRunner(kills=kills)
        cold = audit_suite(cold_runner, "s", code, [gap, covered],
                           existing_kills={covered.id}, cache=store,
                           subject_commit="deadbeef")
        assert cold_runner.mutant_runs == 2

        warm_runner = FakeRunner(kills=kills)
        warm = audit_suite(warm_runner, "s", code, [gap, covered],
                           existing_kills={covered.id}, cache=store,
                           subject_commit="deadbeef")

    assert warm_runner.mutant_runs == 0, "a warm run must not execute anything"
    assert warm_runner._clean_calls == {}, "fitness probes must be reused too"
    assert [t.to_dict() for t in warm.tests] == [t.to_dict() for t in cold.tests]


def test_caching_never_changes_a_verdict(tmp_path):
    """The exit criterion for this work is 'never lose a kill'. The cached and
    uncached paths must agree test-for-test and fault-for-fault."""
    from placebo.cache import ResultCache

    faults = [fault(f"f{i}") for i in range(6)]
    code = suite("test_a", "test_b", "test_c")
    kills = {
        faults[0].id: ["test_a"],
        faults[1].id: ["test_a", "test_b"],
        faults[2].id: ["test_c"],
        faults[3].id: [],
    }
    existing = {faults[2].id}

    uncached = audit_suite(FakeRunner(kills=kills), "s", code, faults, existing)
    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        cached = audit_suite(FakeRunner(kills=kills), "s", code, faults, existing,
                             cache=store, subject_commit="c")

    assert [t.to_dict() for t in cached.tests] == [t.to_dict() for t in uncached.tests]
    assert cached.summary() == uncached.summary()


def test_editing_one_test_reuses_the_other_tests_fitness_results(tmp_path):
    """Fitness is keyed per test, so a one-line edit costs one re-probe rather
    than re-running the whole patch."""
    from placebo.cache import ResultCache

    gap = fault("gap")
    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        audit_suite(FakeRunner(kills={gap.id: ["test_a"]}), "s",
                    suite("test_a", "test_b"), [gap], set(),
                    cache=store, subject_commit="c")

        edited = suite("test_a", "test_b").replace(
            "def test_b():\n    assert True", "def test_b():\n    assert 1 == 1")
        runner = FakeRunner(kills={gap.id: ["test_a"]})
        audit_suite(runner, "s", edited, [gap], set(), cache=store, subject_commit="c")

    # test_a's probe is unchanged and reused; only test_b is probed again.
    assert set(runner._clean_calls) == {"test_b"}


def test_an_edited_patch_reruns_the_fault_matrix(tmp_path):
    """The matrix is keyed on the whole patch, because which test failed can
    change when any test in the file changes."""
    from placebo.cache import ResultCache

    gap = fault("gap")
    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        audit_suite(FakeRunner(kills={gap.id: ["test_a"]}), "s", suite("test_a"),
                    [gap], set(), cache=store, subject_commit="c")

        runner = FakeRunner(kills={gap.id: ["test_a"]})
        audit_suite(runner, "s", suite("test_a", "test_b"), [gap], set(),
                    cache=store, subject_commit="c")

    assert runner.mutant_runs == 1, "the patch changed, so the matrix is not reusable"


def test_a_different_subject_commit_does_not_reuse_results(tmp_path):
    from placebo.cache import ResultCache

    gap = fault("gap")
    code = suite("test_a")
    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        audit_suite(FakeRunner(kills={gap.id: ["test_a"]}), "s", code, [gap], set(),
                    cache=store, subject_commit="commit_a")
        runner = FakeRunner(kills={gap.id: ["test_a"]})
        audit_suite(runner, "s", code, [gap], set(),
                    cache=store, subject_commit="commit_b")

    assert runner.mutant_runs == 1


# -- coverage-based selection ----------------------------------------------


def _map(attribution: dict[int, set[str]], tests: set[str], complete: bool = True):
    """A coverage map attributing subject lines to tests."""
    from placebo.selection import CoverageMap

    cmap = CoverageMap(all_tests=set(tests), complete=complete)
    cmap.lines = {"pkg/m.py": dict(attribution)}
    return cmap


def _fault_at(line: int):
    from placebo.mutation.models import Mutant, OperatorFamily

    return Mutant(file="pkg/m.py", qualname=f"m.f{line}",
                  operator=OperatorFamily.ARITHMETIC, lineno=line, col=0,
                  span_start=line, span_end=line + 1, original="+",
                  replacement="-", subject_commit=COMMIT)


def test_selection_runs_only_the_tests_that_reach_the_fault():
    f = _fault_at(10)
    runner = FakeRunner(kills={f.id: ["test_a"]})
    audit = audit_suite(runner, "s", suite("test_a", "test_b"), [f], set(),
                        coverage_map=_map({10: {"test_a"}}, {"test_a", "test_b"}))

    assert runner.last_selection == ["tests/test_placebo_audit.py::test_a"]
    assert next(t for t in audit.tests if t.name == "test_a").verdict is Verdict.VALUABLE


def test_a_fault_no_eligible_test_reaches_is_skipped_without_executing():
    """The saving that matters, and it must be visible in the summary rather
    than silently shrinking the corpus."""
    f = _fault_at(10)
    runner = FakeRunner(kills={f.id: ["test_a"]})
    audit = audit_suite(runner, "s", suite("test_a"), [f], set(),
                        coverage_map=_map({10: set()}, set()))

    assert runner.mutant_runs == 0
    assert audit.summary()["faults_skipped_by_selection"] == 1
    assert audit.summary()["fault_corpus"] == 1, "the corpus is still reported in full"


def test_an_unattributed_line_runs_the_whole_patch():
    """Import-time lines name no test, so narrowing would be a guess."""
    f = _fault_at(1)
    runner = FakeRunner(kills={f.id: ["test_b"]})
    audit_suite(runner, "s", suite("test_a", "test_b"), [f], set(),
                coverage_map=_map({1: set()}, {"test_a", "test_b"}))

    assert runner.last_selection == [AUDIT_PATH], "whole file, not a node id list"


def test_selection_never_loses_a_kill():
    """The exit criterion. A truthful map must produce exactly the verdicts the
    exhaustive run produces."""
    faults = [_fault_at(n) for n in (10, 11, 12, 13)]
    code = suite("test_a", "test_b", "test_c")
    kills = {
        faults[0].id: ["test_a"],
        faults[1].id: ["test_b"],
        faults[2].id: ["test_a", "test_c"],
    }
    truthful = _map({10: {"test_a"}, 11: {"test_b"},
                     12: {"test_a", "test_c"}, 13: {"test_c"}},
                    {"test_a", "test_b", "test_c"})

    exhaustive = audit_suite(FakeRunner(kills=kills), "s", code, faults, set())
    selected_runner = FakeRunner(kills=kills)
    selected = audit_suite(selected_runner, "s", code, faults, set(),
                           coverage_map=truthful)

    assert [t.to_dict() for t in selected.tests] == [t.to_dict() for t in exhaustive.tests]
    assert selected_runner.tests_executed < len(faults) * 3, "and do less work"


def test_an_incomplete_map_falls_back_to_the_exhaustive_run():
    f = _fault_at(10)
    runner = FakeRunner(kills={f.id: ["test_a"]})
    audit_suite(runner, "s", suite("test_a", "test_b"), [f], set(),
                coverage_map=_map({10: {"test_a"}}, {"test_a", "test_b"},
                                  complete=False))

    assert runner.last_selection == [AUDIT_PATH]


# -- time budget -----------------------------------------------------------


class SlowRunner(FakeRunner):
    """A runner whose fault executions consume measurable wall time."""

    def __init__(self, *args, seconds: float = 0.02, **kwargs):
        super().__init__(*args, **kwargs)
        self.seconds = seconds

    def run_mutant(self, mutant, selection=None, extra=None):
        import time

        time.sleep(self.seconds)
        return super().run_mutant(mutant, selection, extra)


def test_a_budget_stops_the_matrix_and_records_how_far_it_got():
    faults = [fault(f"f{i}") for i in range(40)]
    runner = SlowRunner(kills={}, seconds=0.02)

    audit = audit_suite(runner, "s", suite("test_a"), faults, set(), budget_s=0.1)
    summary = audit.summary()

    assert summary["budget_exhausted"] is True
    assert 0 < summary["faults_evaluated"] < len(faults)
    assert summary["fault_corpus"] == 40, "the full corpus is still reported"
    assert 0 < summary["corpus_coverage"] < 1


def test_a_budget_that_is_never_reached_evaluates_everything():
    faults = [fault(f"f{i}") for i in range(3)]
    audit = audit_suite(FakeRunner(), "s", suite("test_a"), faults, set(),
                        budget_s=60)
    summary = audit.summary()
    assert summary["budget_exhausted"] is False
    assert summary["faults_evaluated"] == 3
    assert summary["corpus_coverage"] == 1.0


def test_a_truncated_audit_says_so_in_the_verdict_note():
    """Otherwise UNPROVEN would read as 'detects nothing' when it actually
    means 'we ran out of time'. That is the same mistake naive truncation of
    the corpus made, and it is the one that inverts the answer."""
    faults = [fault(f"f{i}") for i in range(40)]
    audit = audit_suite(SlowRunner(kills={}, seconds=0.02), "s", suite("test_a"),
                        faults, set(), budget_s=0.1)

    note = audit.tests[0].note
    assert audit.tests[0].verdict is Verdict.UNPROVEN
    assert "time budget ran out" in note
    assert "of 40" in note


def test_no_budget_means_no_truncation_claim():
    audit = audit_suite(FakeRunner(), "s", suite("test_a"),
                        [fault("f")], set())
    assert audit.summary()["budget_exhausted"] is False
    assert "budget" not in audit.tests[0].note


# -- parallel execution and resume -----------------------------------------


def test_worker_count_never_changes_a_verdict():
    """The exit criterion for parallelism. Executions are independent, so the
    only thing more workers may change is how long it takes."""
    faults = [fault(f"f{i}") for i in range(24)]
    code = suite("test_a", "test_b", "test_c")
    kills = {
        faults[0].id: ["test_a"],
        faults[1].id: ["test_a", "test_b"],
        faults[2].id: ["test_c"],
        faults[5].id: ["test_b"],
        faults[9].id: ["test_a", "test_c"],
    }
    existing = {faults[2].id}

    serial = audit_suite(FakeRunner(kills=kills), "s", code, faults, existing)
    for count in (2, 4, 8):
        pool = [FakeRunner(kills=kills) for _ in range(count)]
        parallel = audit_suite(pool[0], "s", code, faults, existing, workers=pool)
        assert [t.to_dict() for t in parallel.tests] == \
            [t.to_dict() for t in serial.tests], f"{count} workers disagreed"


def test_detected_fault_lists_are_ordered_identically_under_parallelism():
    """Order matters because these lists are serialised into evidence. A set
    comparison would pass while the artifact churned on every run."""
    faults = [fault(f"f{i}") for i in range(12)]
    code = suite("test_a")
    kills = {f.id: ["test_a"] for f in faults}

    serial = audit_suite(FakeRunner(kills=kills), "s", code, faults, set())
    pool = [FakeRunner(kills=kills) for _ in range(6)]
    parallel = audit_suite(pool[0], "s", code, faults, set(), workers=pool)

    assert parallel.tests[0].detects == serial.tests[0].detects


def test_every_worker_is_used():
    faults = [fault(f"f{i}") for i in range(30)]
    pool = [FakeRunner(kills={}) for _ in range(4)]
    audit_suite(pool[0], "s", suite("test_a"), faults, set(), workers=pool)
    assert all(w.mutant_runs > 0 for w in pool), "a worker sat idle"
    assert sum(w.mutant_runs for w in pool) == len(faults)


def test_an_interrupted_audit_resumes_instead_of_restarting(tmp_path):
    """Every fault result is written when it is known, so a run killed part
    way through leaves that work recorded for the next one."""
    from placebo.cache import ResultCache

    faults = [fault(f"f{i}") for i in range(20)]
    code = suite("test_a")
    kills = {faults[0].id: ["test_a"]}

    class Interrupting(FakeRunner):
        """Stops abruptly after a few faults, like a killed process."""

        def run_mutant(self, mutant, selection=None, extra=None):
            if self.mutant_runs >= 8:
                raise KeyboardInterrupt("interrupted")
            return super().run_mutant(mutant, selection, extra)

    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        with pytest.raises(KeyboardInterrupt):
            audit_suite(Interrupting(kills=kills), "s", code, faults, set(),
                        cache=store, subject_commit="c")
        completed = store.entries()
        assert completed >= 8, "finished work was not recorded before the stop"

        resumed_runner = FakeRunner(kills=kills)
        resumed = audit_suite(resumed_runner, "s", code, faults, set(),
                              cache=store, subject_commit="c")

    assert resumed_runner.mutant_runs < len(faults), \
        "the resumed run re-executed everything"
    assert resumed.tests[0].detects == [faults[0].id]


def test_a_resumed_audit_matches_an_uninterrupted_one(tmp_path):
    from placebo.cache import ResultCache

    faults = [fault(f"f{i}") for i in range(15)]
    code = suite("test_a", "test_b")
    kills = {faults[1].id: ["test_a"], faults[4].id: ["test_b"]}

    clean = audit_suite(FakeRunner(kills=kills), "s", code, faults, set())

    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        # A first pass that only gets partway, simulated with a tight budget.
        audit_suite(SlowRunner(kills=kills, seconds=0.02), "s", code, faults,
                    set(), cache=store, subject_commit="c", budget_s=0.05)
        resumed = audit_suite(FakeRunner(kills=kills), "s", code, faults,
                              set(), cache=store, subject_commit="c")

    assert [t.to_dict() for t in resumed.tests] == [t.to_dict() for t in clean.tests]


def test_parallel_workers_share_one_cache_without_losing_results(tmp_path):
    from placebo.cache import ResultCache

    faults = [fault(f"f{i}") for i in range(30)]
    code = suite("test_a")
    kills = {f.id: ["test_a"] for f in faults[:10]}

    with ResultCache(tmp_path / "c.sqlite", "fp") as store:
        pool = [FakeRunner(kills=kills) for _ in range(5)]
        first = audit_suite(pool[0], "s", code, faults, set(), workers=pool,
                            cache=store, subject_commit="c")

        warm = [FakeRunner(kills=kills) for _ in range(5)]
        second = audit_suite(warm[0], "s", code, faults, set(), workers=warm,
                             cache=store, subject_commit="c")

    assert sum(w.mutant_runs for w in warm) == 0, "a warm parallel run executed"
    assert [t.to_dict() for t in second.tests] == [t.to_dict() for t in first.tests]

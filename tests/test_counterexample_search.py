"""Tests for the deterministic counterexample search.

This module produces the headline result: six of six confirmed gaps closed
with zero model calls. `scripts/run_gap_search.py` proves that end to end in
CI, but an end-to-end script only shows that the answer came out right once.
These tests pin the properties the claim actually rests on.

Two of them are regression tests for mistakes that were made and measured:

  * Sorting the whole pool by length let short, irrelevant expressions crowd
    out the targeted ones before the budget was reached, which hid the
    build-metadata and error-message witnesses on the first run.
  * Asserting only an exception *type* cannot separate a mutant that changes
    only the exception *message*, which is the case `pytest.raises(TypeError)`
    structurally cannot catch.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.models import Mutant, OperatorFamily  # noqa: E402
from placebo.search.counterexample import (  # noqa: E402
    SearchResult,
    candidate_pool,
    synthesize_from_witness,
)
from placebo.verification.prober import Observation  # noqa: E402

COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"


def make_mutant(qualname: str, operator=OperatorFamily.COMPARISON_BOUNDARY) -> Mutant:
    return Mutant(
        file="semver/version.py",
        qualname=qualname,
        operator=operator,
        lineno=1,
        col=0,
        span_start=0,
        span_end=1,
        original="<",
        replacement="<=",
        subject_commit=COMMIT,
    )


# -- the candidate pool ----------------------------------------------------


def test_pool_is_deterministic():
    """The claim is 'reproducible, zero model calls'. Order must not drift."""
    mutant = make_mutant("Version.match")
    assert candidate_pool(mutant) == candidate_pool(mutant)


def test_pool_has_no_duplicates():
    pool = candidate_pool(make_mutant("Version.compare"))
    assert len(pool) == len(set(pool))


def test_pool_respects_its_budget():
    pool = candidate_pool(make_mutant("Version.match"), budget=25)
    assert len(pool) == 25


def test_relevant_templates_come_first():
    """Relevance tier before cost, not cost alone.

    Sorting the whole pool by length is what hid two witnesses originally, so
    this asserts the tier ordering rather than the sort.
    """
    pool = candidate_pool(make_mutant("Version.match"))
    first_match = next(i for i, e in enumerate(pool) if ".match(" in e)
    first_other = next(
        (i for i, e in enumerate(pool) if ".match(" not in e), len(pool)
    )
    assert first_match < first_other, "match probes must precede unrelated ones"


def test_error_probes_lead_for_parse():
    """`parse` fails on the exception path, so invalid input must come first."""
    pool = candidate_pool(make_mutant("Version.parse"))
    assert ".parse(" in pool[0]
    assert any("not-a-version" in e for e in pool[:10])


def test_first_tier_is_ordered_simplest_first():
    """The reported witness is meant to be the simplest that works."""
    pool = candidate_pool(make_mutant("Version.match"))
    tier = [e for e in pool if ".match(" in e]
    assert tier == sorted(tier, key=lambda e: (len(e), e))


def test_unknown_function_still_yields_candidates():
    """An unhinted function must degrade to the generic families, not to []."""
    assert candidate_pool(make_mutant("Version.some_unhinted_method"))


# -- SearchResult ----------------------------------------------------------


def _observation(expr: str, clean: str, mutant: str, clean_ok: bool = True) -> Observation:
    return Observation(
        expr=expr,
        clean_repr=clean,
        clean_ok=clean_ok,
        mutant_repr=mutant,
        mutant_ok=clean_ok,
    )


def test_result_reports_not_found_without_a_witness():
    result = SearchResult("abc", 42, None, [])
    assert not result.found
    assert result.to_dict()["witness"] is None
    assert result.to_dict()["candidates_tried"] == 42


def test_result_serialises_its_witness():
    obs = _observation("semver.Version.parse('1.0.0')", "True", "False")
    result = SearchResult("abc", 3, obs, [obs])
    payload = result.to_dict()
    assert payload["found"] is True
    assert payload["distinguishing_count"] == 1
    assert payload["witness"]["distinguishes"] is True


# -- synthesis -------------------------------------------------------------


def test_synthesis_returns_nothing_without_a_witness():
    """No witness means no evidence, so it must not emit a test that passes
    for the wrong reason."""
    assert synthesize_from_witness(make_mutant("Version.match"),
                                   SearchResult("abc", 10, None, []),
                                   "test_x") == ""


def test_synthesised_test_is_valid_python():
    obs = _observation('semver.Version.parse("0.0.0").match(">=0.0.0")', "True", "False")
    code = synthesize_from_witness(
        make_mutant("Version.match"), SearchResult("abc", 1, obs, [obs]), "test_gap"
    )
    ast.parse(code)
    assert "def test_gap():" in code
    assert "assert repr(" in code


def test_synthesis_asserts_the_error_message_not_just_the_type():
    """The regression this guards.

    Both the clean and faulty versions raise TypeError for this input and only
    the message differs, so a test that asserted the type alone would pass
    against the fault it claims to detect.
    """
    obs = Observation(
        expr="semver.Version.parse(3.14)",
        clean_repr="TypeError: not expecting type 'float'",
        clean_ok=False,
        mutant_repr="TypeError: not expecting type <class 'float'>",
        mutant_ok=False,
    )
    code = synthesize_from_witness(
        make_mutant("Version.parse"), SearchResult("abc", 1, obs, [obs]), "test_msg"
    )
    ast.parse(code)
    assert "pytest.raises(TypeError)" in code
    assert "str(excinfo.value) ==" in code, "type alone cannot detect this fault"
    assert "not expecting type 'float'" in code


def test_synthesis_corroborates_with_extra_inputs():
    """The witness is the minimal case; extras guard against a coincidence."""
    a = _observation("semver.Version.parse('0.0.0')", "1", "2")
    b = _observation("semver.Version.parse('1.0.0')", "3", "4")
    c = _observation("semver.Version.parse('2.0.0')", "5", "6")
    code = synthesize_from_witness(
        make_mutant("Version.parse"), SearchResult("abc", 3, a, [a, b, c]), "test_x"
    )
    ast.parse(code)
    assert code.count("assert repr(") == 3


def test_synthesis_caps_the_number_of_corroborating_inputs():
    obs = [_observation(f"semver.Version.parse('{i}.0.0')", str(i), str(i + 1))
           for i in range(9)]
    code = synthesize_from_witness(
        make_mutant("Version.parse"), SearchResult("abc", 9, obs[0], obs),
        "test_x", extra=2,
    )
    assert code.count("assert repr(") == 3


def test_synthesised_test_names_the_fault_it_detects():
    """Every generated test must carry its reason, or a reviewer cannot judge
    it."""
    mutant = make_mutant("Version.match")
    obs = _observation("semver.Version.parse('0.0.0')", "True", "False")
    code = synthesize_from_witness(mutant, SearchResult("abc", 1, obs, [obs]), "test_x")
    assert mutant.label in code

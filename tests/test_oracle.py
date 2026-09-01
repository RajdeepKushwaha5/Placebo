"""Tests for oracle levels and brittleness policy.

The module's whole purpose is to stop a snapshot being presented as verified
correctness, so the tests are weighted toward *refusing to promote*. Two of
them are regressions for overclaims this classifier actually made when it was
first run against the project's own generated patch:

  * `assert repr(a < b) == "False"` was read as metamorphic, because walking
    the tree found the inner `<` and ignored that the assertion compares
    against a string literal.
  * `assert str(x) == pytest.raises(...)`, which is broken code, was read as
    differential, because `str` and `pytest` looked like two implementations.

Both would have attached a stronger claim than the evidence supports, which is
the one failure mode this module exists to prevent.
"""

from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.oracle import (  # noqa: E402
    OracleLevel,
    classify,
    detect_brittleness,
    report_suite,
    summarise,
)


def one(source: str):
    """Parse a single test function from source."""
    tree = ast.parse(textwrap.dedent(source))
    return next(n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


# -- levels ----------------------------------------------------------------


def test_a_literal_expected_value_is_a_snapshot():
    level, reason = classify(one('''
        def test_x():
            assert semver.bump_minor("1.2.3") == "1.3.0"
    '''))
    assert level is OracleLevel.SNAPSHOT
    assert not level.claims_correctness
    assert "current behaviour" in reason


def test_a_relation_between_two_executions_is_metamorphic():
    level, _ = classify(one('''
        def test_x():
            assert semver.parse(str(semver.parse("1.2.3"))) == semver.parse("1.2.3")
    '''))
    assert level is OracleLevel.METAMORPHIC
    assert level.claims_correctness


def test_agreement_with_another_implementation_is_differential():
    level, reason = classify(one('''
        def test_x():
            assert semver.compare("1.0.0", "2.0.0") == reference.compare("1.0.0", "2.0.0")
    '''))
    assert level is OracleLevel.DIFFERENTIAL
    assert "reference" in reason


def test_citing_an_external_source_is_a_specification():
    level, reason = classify(one('''
        def test_x():
            """Per the specification, build metadata is ignored in precedence."""
            assert semver.compare("1.0.0+a", "1.0.0+b") == 0
    '''))
    assert level is OracleLevel.SPECIFICATION
    assert "external source" in reason


def test_levels_are_ordered_by_strength():
    assert OracleLevel.SPECIFICATION < OracleLevel.SNAPSHOT
    assert [level.claims_correctness for level in OracleLevel] == [
        True, True, True, False
    ]


# -- refusing to promote ---------------------------------------------------


def test_a_comparison_nested_inside_a_call_is_not_the_assertion():
    """Regression: `assert repr(a < b) == "False"` records a string. Reading
    its inner `<` as the assertion promoted a snapshot to metamorphic."""
    level, _ = classify(one('''
        def test_x():
            assert repr(semver.parse("1.0.0") < semver.parse("1.0.0")) == 'False'
    '''))
    assert level is OracleLevel.SNAPSHOT


def test_builtins_and_the_test_framework_are_not_implementations():
    """Regression: `str(x) == pytest.raises(...)` is broken code, not a
    differential oracle."""
    level, _ = classify(one('''
        def test_x():
            assert str(semver.parse("5")) == pytest.raises(ValueError)
    '''))
    assert level is OracleLevel.SNAPSHOT


def test_a_conversion_of_the_same_subject_is_not_differential():
    level, _ = classify(one('''
        def test_x():
            assert str(semver.parse("1.2.3")) == repr(semver.parse("1.2.3"))
    '''))
    assert level is not OracleLevel.DIFFERENTIAL


def test_a_test_with_no_calls_is_still_a_snapshot():
    level, _ = classify(one('''
        def test_x():
            assert 1 == 1
    '''))
    assert level is OracleLevel.SNAPSHOT


# -- brittleness -----------------------------------------------------------


def test_exact_exception_wording_is_flagged():
    warnings = detect_brittleness(one('''
        def test_x():
            with pytest.raises(TypeError) as excinfo:
                semver.parse(3.14)
            assert str(excinfo.value) == "not expecting type 'float'"
    '''))
    assert any(w.kind == "exception-message" for w in warnings)


def test_repr_comparison_is_flagged_as_a_display_detail():
    warnings = detect_brittleness(one('''
        def test_x():
            assert repr(semver.parse("1.2.3")) == 'Version(major=1)'
    '''))
    assert any(w.kind == "representation" for w in warnings)


def test_wall_clock_values_are_flagged():
    warnings = detect_brittleness(one('''
        def test_x():
            assert record.created == datetime.now()
    '''))
    assert any(w.kind == "nondeterministic" for w in warnings)


def test_serialisation_output_is_flagged():
    warnings = detect_brittleness(one('''
        def test_x():
            assert json.dumps(payload) == '{"a": 1}'
    '''))
    assert any(w.kind == "serialisation" for w in warnings)


def test_a_plain_value_assertion_is_not_brittle():
    assert detect_brittleness(one('''
        def test_x():
            assert semver.bump_minor("1.2.3") == "1.3.0"
    ''')) == []


def test_a_call_outside_a_comparison_is_not_flagged():
    """`str()` used to build an argument is not an assertion about display."""
    warnings = detect_brittleness(one('''
        def test_x():
            parsed = semver.parse(str(raw))
            assert parsed.major == 1
    '''))
    assert not any(w.kind == "representation" for w in warnings)


def test_one_line_reports_each_problem_once():
    warnings = detect_brittleness(one('''
        def test_x():
            assert repr(a) == repr(b)
    '''))
    assert len([w for w in warnings if w.kind == "representation"]) == 1


def test_warnings_are_ordered_by_line():
    warnings = detect_brittleness(one('''
        def test_x():
            assert json.dumps(a) == '{}'
            assert repr(b) == 'x'
    '''))
    assert [w.line for w in warnings] == sorted(w.line for w in warnings)


# -- suite-level reporting -------------------------------------------------


def test_report_covers_every_test_and_is_serialisable():
    import json

    reports = report_suite(textwrap.dedent('''
        def test_a():
            assert semver.bump_minor("1.2.3") == "1.3.0"

        def test_b():
            """Per the specification, this holds."""
            assert semver.compare("1.0.0", "1.0.0") == 0

        def helper():
            return 1
    '''))
    assert [r.test for r in reports] == ["test_a", "test_b"], "helpers are not tests"
    json.dumps([r.to_dict() for r in reports])
    assert reports[0].to_dict()["claims_correctness"] is False
    assert reports[1].to_dict()["claims_correctness"] is True


def test_unparseable_source_reports_nothing_rather_than_raising():
    assert report_suite("def (((") == []


def test_summary_counts_levels_and_brittleness():
    reports = report_suite(textwrap.dedent('''
        def test_a():
            assert repr(semver.parse("1.2.3")) == 'Version(major=1)'

        def test_b():
            assert semver.bump_minor("1.2.3") == "1.3.0"
    '''))
    summary = summarise(reports)
    assert summary["tests"] == 2
    assert summary["snapshot_only"] == 2
    assert summary["brittle"] == 1
    assert summary["by_level"]["L4 snapshot"] == 2


def test_the_projects_own_generated_patch_is_entirely_snapshot():
    """The honest self-assessment. These tests take expected values by
    executing the implementation, so none of them can claim correctness."""
    patch = ROOT / "artifacts" / "suites" / "as_generated_patch.py"
    reports = report_suite(patch.read_text(encoding="utf-8"))
    summary = summarise(reports)

    assert summary["tests"] == 33
    assert summary["snapshot_only"] == 33, "no generated test may claim more"
    assert not any(r.level.claims_correctness for r in reports)

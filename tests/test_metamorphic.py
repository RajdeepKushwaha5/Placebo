"""Tests for the metamorphic oracle.

A metamorphic property asserts a relationship between executions rather than a
recorded output, which is the only reason it can be called a stronger oracle
than a snapshot. Two things must therefore be true and are tested here:

  * a property that does not hold on correct code is not a detector. If it is
    unsound, its failure under a fault says nothing, and crediting it would be
    the tool inventing evidence.
  * a synthesized property test must contain no recorded expected value. If a
    literal leaked into one, it would be a snapshot wearing a stronger label,
    which is worse than an honestly labelled snapshot.

The prober is faked, so these exercise the attribution logic rather than
re-testing execution. `scripts/run_metamorphic.py` covers the real path in CI.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.models import Mutant, OperatorFamily  # noqa: E402
from placebo.search import metamorphic as mm  # noqa: E402
from placebo.verification.prober import Observation  # noqa: E402

COMMIT = "0" * 40


def a_mutant() -> Mutant:
    return Mutant(
        file="semver/version.py", qualname="Version.compare",
        operator=OperatorFamily.COMPARISON_BOUNDARY, lineno=1, col=0,
        span_start=0, span_end=1, original="<", replacement="<=",
        subject_commit=COMMIT,
    )


def fake_observe(mapping: dict[str, tuple[str, str]]):
    """Return an `observe` that reports declared clean/mutant values.

    `mapping` maps an expression to (clean_repr, mutant_repr). Anything absent
    holds on both sides, which is the common case.
    """
    def _observe(_runner, _mutant, expressions, **_kwargs):
        out = []
        for expr in expressions:
            clean, mutated = mapping.get(expr, ("True", "True"))
            out.append(Observation(
                expr=expr, clean_repr=clean, clean_ok=clean != "ERROR",
                mutant_repr=mutated, mutant_ok=mutated != "ERROR",
            ))
        return out
    return _observe


def comparisons(expression: str) -> list[ast.Compare]:
    """Every comparison in an expression.

    A property is usually one comparison, but two of them are `X and Y`, so
    the check has to look at each conjunct rather than assume a single top
    level Compare.
    """
    tree = ast.parse(expression, mode="eval")
    return [n for n in ast.walk(tree) if isinstance(n, ast.Compare)]


def recorded_literals(compare: ast.Compare) -> list[ast.Constant]:
    """Operands that are a bare literal answer rather than an execution.

    A version string is an input and appears inside a call. Integers are the
    algebra of the property itself, as in `minor == minor + 1`, and `None` is a
    field value, not a recorded output.
    """
    out = []
    for operand in [compare.left, *compare.comparators]:
        if isinstance(operand, ast.Constant) and not isinstance(
                operand.value, (int, bool, type(None))):
            out.append(operand)
    return out


# -- the property set itself -----------------------------------------------


def test_every_property_is_a_formattable_boolean_expression():
    for name, description, template in mm.PROPERTIES:
        assert name and description, f"{name} lacks a description"
        rendered = template.format(a="1.2.3", b="2.0.0")
        found = comparisons(rendered)
        assert found, f"{name} asserts no relationship between executions"
        # Both sides must actually run something, or it is not metamorphic.
        for compare in found:
            calls = [
                n for operand in [compare.left, *compare.comparators]
                for n in ast.walk(operand) if isinstance(n, ast.Call)
            ]
            assert calls, f"{name} has a comparison that executes nothing"


def test_no_property_hardcodes_an_expected_value():
    """The whole claim. A literal on either side of the top-level comparison
    would make it a snapshot, not a metamorphic relation."""
    offenders = []
    for name, _desc, template in mm.PROPERTIES:
        for compare in comparisons(template.format(a="1.2.3", b="2.0.0")):
            if recorded_literals(compare):
                offenders.append(name)
    assert not offenders, f"these encode a literal answer: {sorted(set(offenders))}"


def test_property_names_are_unique():
    names = [name for name, _d, _t in mm.PROPERTIES]
    assert len(names) == len(set(names))


def test_instantiate_is_deterministic_and_bounded():
    first = mm.instantiate(limit_pairs=3)
    assert first == mm.instantiate(limit_pairs=3), "instantiation must not drift"
    assert len(first) == len(mm.PROPERTIES) * 3


def test_instantiate_with_no_pairs_yields_nothing():
    """An empty candidate domain must produce no instances rather than raise."""
    assert mm.instantiate(limit_pairs=0) == []


def test_instantiate_substitutes_both_operands():
    rendered = [expr for _name, expr in mm.instantiate(limit_pairs=1)]
    assert not any("{a}" in e or "{b}" in e for e in rendered)


# -- soundness gates detection ---------------------------------------------


def test_a_property_that_holds_and_is_violated_detects(monkeypatch):
    instances = mm.instantiate(limit_pairs=1)
    target = instances[0][1]
    monkeypatch.setattr(mm, "observe", fake_observe({target: ("True", "False")}))

    results = mm.check_properties(None, a_mutant(), limit_pairs=1)
    detected = [r for r in results if r.detects]
    assert len(detected) == 1
    assert detected[0].example == target


def test_an_unsound_property_never_detects(monkeypatch):
    """It fails under the fault, but it also fails on correct code, so its
    failure is not evidence about the fault."""
    instances = mm.instantiate(limit_pairs=1)
    target = instances[0][1]
    monkeypatch.setattr(mm, "observe", fake_observe({target: ("False", "False")}))

    results = mm.check_properties(None, a_mutant(), limit_pairs=1)
    unsound = next(r for r in results if r.name == instances[0][0])
    assert not unsound.holds_on_clean
    assert not unsound.detects, "an unsound property must never be credited"


def test_a_property_that_errors_on_clean_code_never_detects(monkeypatch):
    instances = mm.instantiate(limit_pairs=1)
    target = instances[0][1]
    monkeypatch.setattr(mm, "observe", fake_observe({target: ("ERROR", "False")}))

    results = mm.check_properties(None, a_mutant(), limit_pairs=1)
    errored = next(r for r in results if r.name == instances[0][0])
    assert not errored.holds_on_clean and not errored.detects


def test_one_unsound_instance_disqualifies_the_whole_property(monkeypatch):
    """A property is only sound if it holds for every input tried, not most."""
    instances = mm.instantiate(limit_pairs=3)
    name = instances[0][0]
    mine = [expr for n, expr in instances if n == name]
    monkeypatch.setattr(mm, "observe", fake_observe({
        mine[0]: ("True", "False"),
        mine[1]: ("False", "False"),   # unsound on this input
        mine[2]: ("True", "True"),
    }))

    results = mm.check_properties(None, a_mutant(), limit_pairs=3)
    result = next(r for r in results if r.name == name)
    assert not result.holds_on_clean and not result.detects


def test_a_property_unaffected_by_the_fault_does_not_detect(monkeypatch):
    monkeypatch.setattr(mm, "observe", fake_observe({}))
    results = mm.check_properties(None, a_mutant(), limit_pairs=2)
    assert results, "properties should still be reported"
    assert not any(r.detects for r in results)
    assert all(r.holds_on_clean for r in results)


def test_attribution_names_the_violating_input(monkeypatch):
    """A detection a reviewer cannot reproduce is not useful, so the example
    must be an instance that actually differed."""
    instances = mm.instantiate(limit_pairs=2)
    name = instances[0][0]
    mine = [expr for n, expr in instances if n == name]
    monkeypatch.setattr(mm, "observe", fake_observe({mine[1]: ("True", "False")}))

    result = next(r for r in mm.check_properties(None, a_mutant(), limit_pairs=2)
                  if r.name == name)
    assert result.detects and result.example == mine[1]


def test_results_are_reported_for_every_property(monkeypatch):
    monkeypatch.setattr(mm, "observe", fake_observe({}))
    results = mm.check_properties(None, a_mutant(), limit_pairs=1)
    assert {r.name for r in results} == {n for n, _d, _t in mm.PROPERTIES}


def test_a_timeout_or_missing_observation_is_skipped(monkeypatch):
    """The prober returns nothing when a batch times out. A property with no
    observation must be omitted rather than counted as holding."""
    def observe_nothing(_runner, _mutant, _expressions, **_kwargs):
        return []

    monkeypatch.setattr(mm, "observe", observe_nothing)
    assert mm.check_properties(None, a_mutant(), limit_pairs=2) == []


def test_results_are_serialisable(monkeypatch):
    import json

    monkeypatch.setattr(mm, "observe", fake_observe({}))
    results = mm.check_properties(None, a_mutant(), limit_pairs=1)
    json.dumps([r.to_dict() for r in results])
    assert results[0].to_dict()["detects"] is False


def test_check_is_deterministic(monkeypatch):
    instances = mm.instantiate(limit_pairs=2)
    monkeypatch.setattr(mm, "observe",
                        fake_observe({instances[0][1]: ("True", "False")}))
    first = [r.to_dict() for r in mm.check_properties(None, a_mutant(), 2)]
    second = [r.to_dict() for r in mm.check_properties(None, a_mutant(), 2)]
    assert first == second


# -- synthesis -------------------------------------------------------------


def synthesized(monkeypatch, mapping) -> str:
    monkeypatch.setattr(mm, "observe", fake_observe(mapping))
    results = mm.check_properties(None, a_mutant(), limit_pairs=2)
    return mm.synthesize_property_test(a_mutant(), results, "test_meta")


def test_a_synthesized_test_is_valid_python(monkeypatch):
    instances = mm.instantiate(limit_pairs=2)
    code = synthesized(monkeypatch, {instances[0][1]: ("True", "False")})
    ast.parse(code)
    assert "def test_meta():" in code


def test_a_synthesized_test_contains_no_recorded_value(monkeypatch):
    """The property that makes this a level-3 oracle. Any bare literal on one
    side of an assertion would mean a snapshot had leaked in."""
    instances = mm.instantiate(limit_pairs=2)
    code = synthesized(monkeypatch, {instances[0][1]: ("True", "False")})

    tree = ast.parse(code)
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    assert asserts, "the synthesized test asserts nothing"
    for node in asserts:
        for compare in [n for n in ast.walk(node) if isinstance(n, ast.Compare)]:
            assert not recorded_literals(compare), \
                f"a recorded value leaked into a metamorphic assertion: {code}"


def test_nothing_is_synthesized_when_no_property_detects(monkeypatch):
    """No detector means no evidence, so it must not emit a test that would
    pass for an unrelated reason."""
    assert synthesized(monkeypatch, {}) == ""


def test_an_unsound_property_is_never_synthesized(monkeypatch):
    instances = mm.instantiate(limit_pairs=2)
    code = synthesized(monkeypatch, {instances[0][1]: ("False", "False")})
    assert code == ""


def test_the_synthesized_test_names_the_fault_and_its_properties(monkeypatch):
    instances = mm.instantiate(limit_pairs=2)
    code = synthesized(monkeypatch, {instances[0][1]: ("True", "False")})
    assert a_mutant().label in code
    description = next(d for n, d, _t in mm.PROPERTIES if n == instances[0][0])
    assert description in code


def test_synthesis_is_deterministic(monkeypatch):
    instances = mm.instantiate(limit_pairs=2)
    mapping = {instances[0][1]: ("True", "False")}
    assert synthesized(monkeypatch, mapping) == synthesized(monkeypatch, mapping)


def test_a_detector_without_an_example_is_not_synthesized():
    """Without a reproducing input there is nothing to assert."""
    result = mm.PropertyResult("p", "desc", holds_on_clean=True,
                               violated_by_fault=True, example="")
    assert result.detects
    assert mm.synthesize_property_test(a_mutant(), [result], "test_x") == ""

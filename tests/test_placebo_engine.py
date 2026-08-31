"""Placebo's own unit tests.

These guard the parts of the system that carry the claims: mutant identity must
be stable, the held-out split must not leak, and the admission gates must reject
tests that cheat.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.agents.test_author import (  # noqa: E402
    extract_code,
    function_contract,
    function_source,
)
from placebo.evaluation.evaluator import assemble_suite  # noqa: E402
from placebo.evaluation.repair import count_tests, keep_green_tests  # noqa: E402
from placebo.mutation.engine import enumerate_file, enumerate_subject  # noqa: E402
from placebo.mutation.split import build_split  # noqa: E402
from placebo.verification.admission import Rejection, _static_checks  # noqa: E402
from placebo.verification.prober import extract_expressions  # noqa: E402

SUBJECT = ROOT / "subject"
TARGET = "semver/version.py"
COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"


@pytest.fixture(scope="module")
def mutants():
    return enumerate_subject(SUBJECT, [TARGET], COMMIT)


# -- mutation engine -------------------------------------------------------


def test_enumeration_is_deterministic(mutants):
    again = enumerate_subject(SUBJECT, [TARGET], COMMIT)
    assert [m.id for m in mutants] == [m.id for m in again]


def test_mutant_ids_are_unique(mutants):
    assert len({m.id for m in mutants}) == len(mutants)


def test_mutant_id_is_content_derived_not_positional(mutants):
    """Reversing the list must not change any id."""
    ids = {m.id for m in mutants}
    assert {m.id for m in reversed(mutants)} == ids


def test_apply_changes_exactly_the_recorded_span(mutants):
    source = (SUBJECT / TARGET).read_text(encoding="utf-8")
    for mutant in mutants[:25]:
        mutated = mutant.apply(source)
        assert mutated != source
        expected_delta = len(mutant.replacement) - len(mutant.original)
        assert len(mutated) - len(source) == expected_delta
        assert mutated[: mutant.span_start] == source[: mutant.span_start]


def test_apply_rejects_stale_span(mutants):
    """A manifest against changed source must fail loudly, not silently."""
    with pytest.raises(ValueError, match="span mismatch"):
        mutants[0].apply("completely different source text")


def test_annotations_are_not_mutated(tmp_path):
    src = tmp_path / "annotated.py"
    src.write_text(
        "from typing import Optional\n"
        "def f(x: int = 1) -> Optional[int]:\n"
        "    y: int = 2\n"
        "    return x + y\n",
        encoding="utf-8",
    )
    found = enumerate_file(src, "annotated.py", COMMIT)
    # The annotation literals must not appear as mutation targets; only the
    # default value, the assigned value and the return expression may.
    assert all("Optional" not in m.original for m in found)
    assert any(m.operator.value == "arithmetic" for m in found)


def test_module_scope_is_not_mutated(tmp_path):
    src = tmp_path / "modlevel.py"
    src.write_text("TIMEOUT = 30\ndef f():\n    return 1\n", encoding="utf-8")
    found = enumerate_file(src, "modlevel.py", COMMIT)
    assert all(m.qualname != "<module>" for m in found)


# -- held-out split --------------------------------------------------------


def test_split_is_disjoint_and_excludes_same_span_siblings(mutants):
    killable = {m.id for m in mutants}
    discovery = mutants[:10]
    split = build_split(discovery, mutants, killable, per_function=3)
    split.assert_disjoint()  # raises on leakage

    discovery_spans = {(m.file, m.span_start, m.span_end) for m in discovery}
    for held in split.held_out:
        assert (held.file, held.span_start, held.span_end) not in discovery_spans


def test_split_fingerprint_changes_with_contents(mutants):
    killable = {m.id for m in mutants}
    a = build_split(mutants[:10], mutants, killable, per_function=3)
    b = build_split(mutants[5:15], mutants, killable, per_function=3)
    assert a.fingerprint != b.fingerprint


def test_split_is_reproducible(mutants):
    killable = {m.id for m in mutants}
    a = build_split(mutants[:10], mutants, killable, per_function=3)
    b = build_split(mutants[:10], mutants, killable, per_function=3)
    assert a.fingerprint == b.fingerprint


# -- admission static gates ------------------------------------------------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("", Rejection.NO_CODE),
        ("def test_x(:\n", Rejection.SYNTAX_ERROR),
        ("import semver\nx = 1\n", Rejection.NO_TEST_FUNCTION),
        ("import pytest\ndef test_x():\n    pytest.skip('nope')\n", Rejection.FORBIDDEN_PATTERN),
        ("import inspect\ndef test_x():\n    assert inspect\n", Rejection.FORBIDDEN_PATTERN),
        ("def test_x():\n    value = 1\n", Rejection.NO_ASSERTION),
    ],
)
def test_static_gates_reject_bad_candidates(code, expected):
    result = _static_checks(code)
    assert result is not None, f"expected rejection {expected}"
    assert result[0] is expected


def test_static_gates_accept_a_real_test():
    code = "import semver\ndef test_x():\n    assert semver.Version.parse('1.2.3').minor == 2\n"
    assert _static_checks(code) is None


# -- agent helpers ---------------------------------------------------------


def test_extract_code_prefers_fenced_block():
    text = "Here you go:\n```python\nimport semver\ndef test_a():\n    assert True\n```\nDone."
    assert extract_code(text).startswith("import semver")
    assert "Here you go" not in extract_code(text)


def test_contract_hides_the_implementation_body():
    """Condition C must not leak current behaviour to the test author."""
    source = function_source(SUBJECT / TARGET, "Version.bump_minor")
    contract = function_contract(SUBJECT / TARGET, "Version.bump_minor")
    assert contract, "contract extraction failed"
    assert "def bump_minor" in contract
    assert "..." in contract
    # Body statements present in the real source must be absent from the contract.
    body_lines = [
        ln.strip() for ln in source.splitlines()
        if ln.strip().startswith("return ") or ln.strip().startswith("cls(")
    ]
    for line in body_lines:
        assert line not in contract


def test_probe_expression_dsl_accepts_semver_calls_and_comparisons():
    text = """```python
semver.Version.parse("1.2.3").bump_minor()
semver.Version.parse("1.0.0") < semver.Version.parse("2.0.0")
```"""
    assert extract_expressions(text) == [
        'semver.Version.parse("1.2.3").bump_minor()',
        'semver.Version.parse("1.0.0") < semver.Version.parse("2.0.0")',
    ]


@pytest.mark.parametrize("payload", [
    "semver.Version.parse(open('secret.txt').read())",
    "(semver.Version, __import__('os').system('whoami'))",
    "semver.__dict__",
    "semver.Version.parse('1.2.3').__class__",
    "'{}'.format(semver.Version.parse('1.2.3'))",
    "semver.Version.parse('1.2.3') if open('x') else semver.Version(1)",
])
def test_probe_expression_dsl_rejects_host_access(payload):
    assert extract_expressions(payload) == []


# -- suite assembly / fair green repair -----------------------------------


def test_assembly_skips_a_malformed_candidate_without_poisoning_valid_ones(mutants):
    malformed = "def test_broken(:\n    assert True\n"
    valid = "import semver\n\ndef test_valid():\n    assert semver.Version.parse('1.2.3').minor == 2\n"
    suite = assemble_suite(
        [(mutants[0], malformed), (mutants[1], valid)], ""
    )
    compile(suite, "<assembled-suite>", "exec")
    assert count_tests(suite) == 1
    assert "test_valid" not in suite  # renamed to a collision-free suite name


def test_count_tests_does_not_credit_unparseable_code():
    assert count_tests("def test_broken(:\n    assert True\n") == 0


def test_green_repair_rejects_an_unparseable_suite_without_running_it():
    repaired, kept, dropped = keep_green_tests(
        object(), "def test_broken(:\n    assert True\n"  # type: ignore[arg-type]
    )
    assert repaired == ""
    assert kept == []
    assert dropped == ["<unparseable_or_no_tests>"]


# -- suite assembly / repair ----------------------------------------------


def test_repair_preserves_fault_annotations(mutants):
    """The `# fault detected:` comments are the the evidence a reviewer reads.

    They are also what the bundle builder reads back to map each test to the
    fault it detects, so losing them in the repair step would silently gut the
    deliverable.
    """
    from placebo.evaluation.evaluator import assemble_suite
    from placebo.evaluation.repair import split_tests

    source = (SUBJECT / TARGET).read_text(encoding="utf-8")
    code = (
        "import semver\n\n"
        "def test_placebo_candidate():\n"
        "    assert semver.Version.parse('1.2.3').minor == 2\n"
    )
    suite = assemble_suite([(m, code) for m in mutants[:3]], source)
    _preamble, tests = split_tests(suite)

    assert len(tests) == 3
    for _name, test_source in tests:
        assert "# mutant id:" in test_source
        assert "# fault detected:" in test_source


# -- marginal-value audit --------------------------------------------------


def _audit_with(records):
    """Build a SuiteAudit from (name, novel_fault_ids, verdict) tuples."""
    from placebo.audit.marginal import SuiteAudit, TestAudit

    audit = SuiteAudit(suite_name="synthetic")
    for name, novel, verdict in records:
        entry = TestAudit(name=name, green_on_clean=True, stable=True)
        entry.novel = list(novel)
        entry.detects = list(novel)
        entry.verdict = verdict
        audit.tests.append(entry)
    return audit


def test_minimization_keeps_a_fault_only_siblings_detect():
    """Regression: dropping every redundant test used to drop the fault too.

    Two tests both detect fault F, so neither is the *unique* detector and both
    classify as REDUNDANT_WITH_SIBLING. Filtering to VALUABLE-only would remove
    both and silently lose F. Minimization must be a set cover.
    """
    from placebo.audit.marginal import Verdict, select_minimal_cover

    audit = _audit_with([
        ("test_unique", ["F1"], Verdict.VALUABLE),
        ("test_sib_a", ["F2"], Verdict.REDUNDANT_WITH_SIBLING),
        ("test_sib_b", ["F2"], Verdict.REDUNDANT_WITH_SIBLING),
    ])
    kept, preserved = select_minimal_cover(audit)

    assert preserved == {"F1", "F2"}
    covered = set()
    for entry in audit.tests:
        if entry.name in kept:
            covered |= set(entry.novel)
    assert covered == preserved, "minimization lost a fault"
    assert "test_unique" in kept
    assert len([n for n in kept if n.startswith("test_sib")]) == 1


def test_minimization_is_deterministic_and_drops_true_duplicates():
    from placebo.audit.marginal import Verdict, select_minimal_cover

    records = [
        ("test_b", ["F1", "F2"], Verdict.REDUNDANT_WITH_SIBLING),
        ("test_a", ["F1"], Verdict.REDUNDANT_WITH_SIBLING),
        ("test_c", ["F2"], Verdict.REDUNDANT_WITH_SIBLING),
    ]
    first, _ = select_minimal_cover(_audit_with(records))
    second, _ = select_minimal_cover(_audit_with(records))
    assert first == second == ["test_b"], "greedy cover should pick the superset test"


def test_harmful_tests_are_never_credited_or_kept():
    from placebo.audit.marginal import Verdict, select_minimal_cover

    audit = _audit_with([
        ("test_red", ["F1"], Verdict.HARMFUL),
        ("test_ok", ["F2"], Verdict.VALUABLE),
    ])
    kept, preserved = select_minimal_cover(audit)
    assert "test_red" not in kept
    assert preserved == {"F2"}, "a test that is red on clean code proves nothing"


def test_minimal_patch_returns_writable_source_not_a_tuple(tmp_path):
    """Regression for the judge-facing ``placebo audit --minimize`` path."""
    from placebo.audit.marginal import Verdict, minimal_patch

    audit = _audit_with([
        ("test_a", ["F1"], Verdict.REDUNDANT_WITH_SIBLING),
        ("test_b", ["F1"], Verdict.REDUNDANT_WITH_SIBLING),
    ])
    source = (
        "import pytest\n\n"
        "def test_a():\n    assert True\n\n"
        "def test_b():\n    assert True\n"
    )

    minimized, kept, preserved = minimal_patch(audit, source)
    output = tmp_path / "patch.minimized.py"
    output.write_text(minimized, encoding="utf-8")

    assert output.read_text(encoding="utf-8") == minimized
    assert len(kept) == 1
    assert preserved == {"F1"}


def test_fault_sampling_never_drops_the_gaps(mutants):
    """Regression: a truncated corpus must not invert the audit's verdict.

    Naive `faults[:limit]` truncates in source order, which can exclude every
    fault the existing suite misses. A patch that closes real gaps is then
    reported as detecting nothing novel - the opposite answer, not a rougher
    one. This was reachable from the documented `placebo audit --faults N`.
    """
    from placebo.audit.marginal import sample_fault_corpus

    # Pretend the suite misses only faults near the end of the file, exactly
    # the ones naive truncation would discard.
    gaps = {m.id for m in mutants[-5:]}
    existing_kills = {m.id for m in mutants if m.id not in gaps}

    naive = mutants[:20]
    assert not (gaps & {m.id for m in naive}), "precondition: naive truncation drops them"

    sampled = sample_fault_corpus(mutants, existing_kills, 20)
    assert len(sampled) <= 20
    assert gaps <= {m.id for m in sampled}, "sampling dropped a known gap"


def test_fault_sampling_is_deterministic_and_ordered(mutants):
    from placebo.audit.marginal import sample_fault_corpus

    existing = {m.id for m in mutants[10:]}
    first = sample_fault_corpus(mutants, existing, 25)
    second = sample_fault_corpus(mutants, existing, 25)
    assert [m.id for m in first] == [m.id for m in second]

    order = {m.id: i for i, m in enumerate(mutants)}
    positions = [order[m.id] for m in first]
    assert positions == sorted(positions), "sample should keep source order"


def test_fault_sampling_is_a_noop_when_limit_exceeds_corpus(mutants):
    from placebo.audit.marginal import sample_fault_corpus

    assert sample_fault_corpus(mutants, set(), 10_000) == mutants
    assert sample_fault_corpus(mutants, set(), 0) == mutants

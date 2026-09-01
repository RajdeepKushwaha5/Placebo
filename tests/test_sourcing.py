"""Tests for sourcing oracles instead of recording behaviour.

Every test this project generates is L4, because its expected values come from
running the implementation. Sourcing is the way out: a repository's own
docstring examples are claims its authors made about intended behaviour, at a
line number anyone can open.

The property that matters most is the citation. A label reading "L1
specification" is worth nothing if the line it names is not where the claim
lives, so most of these tests check that the citation is verifiable rather than
merely present. Two earlier implementations produced citations that pointed at
the wrong line, and both looked completely plausible in the output.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.oracle import OracleLevel  # noqa: E402
from placebo.sourcing import (  # noqa: E402
    OracleCandidate,
    from_docstrings,
    source_oracles,
)

MODULE = textwrap.dedent('''\
    """Module docstring with no examples."""


    def bump(version):
        """Raise the minor part.

        >>> bump("1.2.3")
        '1.3.0'
        """
        return version


    def described(value):
        """Uses setup before asserting.

        >>> base = "2.0.0"
        >>> described(base)
        '2.0.0'
        """
        return value


    def raises(value):
        """Documents an exception.

        >>> raises(None)
        Traceback (most recent call last):
        ValueError: no
        """
        raise ValueError("no")


    def undocumented(value):
        """No examples here at all."""
        return value
    ''')


def write(tmp_path: Path, text: str = MODULE) -> Path:
    path = tmp_path / "mod.py"
    path.write_text(text, encoding="utf-8")
    return path


# -- extraction ------------------------------------------------------------


def test_documented_examples_become_specification_candidates(tmp_path):
    candidates = from_docstrings(write(tmp_path))
    assert candidates, "no documented examples were found"
    assert all(c.level is OracleLevel.SPECIFICATION for c in candidates)
    assert all(c.confidence == "contract-backed" for c in candidates)


def test_every_citation_points_at_the_line_it_claims(tmp_path):
    """The load-bearing property. A citation nobody can follow is decoration."""
    path = write(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()

    for candidate in from_docstrings(path):
        number = int(candidate.source.split(":")[1])
        assert 1 <= number <= len(lines), f"{candidate.source} is out of range"
        assert candidate.expression in lines[number - 1], (
            f"{candidate.source} claims {candidate.expression!r} but the file "
            f"has {lines[number - 1].strip()!r}"
        )


def test_the_real_subject_yields_citations_that_all_check_out():
    """Against the vendored subject rather than a fixture, because the two
    line-number bugs both passed on simple input and failed on real files."""
    target = ROOT / "subject" / "semver" / "version.py"
    lines = target.read_text(encoding="utf-8").splitlines()

    candidates = from_docstrings(target)
    assert len(candidates) >= 15, "the subject documents more examples than this"
    wrong = [
        c.source for c in candidates
        if c.expression not in lines[int(c.source.split(":")[1]) - 1]
    ]
    assert not wrong, f"citations pointing at the wrong line: {wrong}"


def test_setup_lines_are_carried_not_asserted(tmp_path):
    """`base = "2.0.0"` states nothing, but later examples need it."""
    candidates = from_docstrings(write(tmp_path))
    described = next(c for c in candidates if "described(" in c.expression)
    assert 'base = "2.0.0"' in described.setup
    assert not any(c.expression.startswith("base =") for c in candidates)


def test_documented_exceptions_are_skipped_rather_than_approximated(tmp_path):
    """An expected traceback is a real claim, but not a value comparison.
    Rendering it as one would produce a test that asserts the wrong shape."""
    candidates = from_docstrings(write(tmp_path))
    assert not any("raises(" in c.expression for c in candidates)


def test_functions_without_examples_contribute_nothing(tmp_path):
    candidates = from_docstrings(write(tmp_path))
    assert not any("undocumented" in c.expression for c in candidates)


def test_an_unreadable_or_unparseable_file_yields_nothing(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text("def (((\n", encoding="utf-8")
    assert from_docstrings(broken) == []
    assert from_docstrings(tmp_path / "absent.py") == []


def test_extraction_is_deterministic(tmp_path):
    path = write(tmp_path)
    assert [c.to_dict() for c in from_docstrings(path)] == \
        [c.to_dict() for c in from_docstrings(path)]


# -- rendering -------------------------------------------------------------


def test_a_rendered_assertion_carries_its_provenance(tmp_path):
    import ast

    candidate = from_docstrings(write(tmp_path))[0]
    rendered = candidate.render()

    assert "# Oracle: L1 specification" in rendered
    assert f"# Source: {candidate.source}" in rendered
    assert "# Confidence: contract-backed" in rendered
    ast.parse("def t():\n" + rendered)


def test_rendering_includes_the_setup_it_depends_on(tmp_path):
    described = next(c for c in from_docstrings(write(tmp_path))
                     if "described(" in c.expression)
    assert 'base = "2.0.0"' in described.render()


def test_a_snapshot_candidate_is_never_marked_cited():
    """L4 has no external authority, so it must not present one."""
    snapshot = OracleCandidate(
        expression="f(1)", expected="2", level=OracleLevel.SNAPSHOT,
        source="observed:runtime", confidence="observed",
    )
    assert not snapshot.cited
    assert not snapshot.level.claims_correctness


# -- reporting -------------------------------------------------------------


def test_the_report_counts_levels_and_is_serialisable(tmp_path):
    report = source_oracles([write(tmp_path)])
    payload = report.to_dict()
    json.dumps(payload)

    assert payload["by_level"]["L1 specification"] == len(report.candidates)
    assert payload["cited"] == len(report.candidates)
    assert report.strongest is OracleLevel.SPECIFICATION


def test_an_empty_repository_reports_no_oracles(tmp_path):
    report = source_oracles([])
    assert report.candidates == []
    assert report.strongest is None

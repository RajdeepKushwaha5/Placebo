"""Tests for coverage-based test selection.

Selection makes the audit faster by not running tests that cannot reach a
fault. That is only worth doing if it is provably conservative, so almost
every test here is about when selection must *refuse* to narrow: an
unattributed line, an unseen line, or a map that failed to build all have to
fall back to the whole suite.

The fixture payloads are the real shape emitted by
`coverage json --show-contexts`, including its `|run` context suffix and its
platform-native path separators.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.mutation.models import Mutant, OperatorFamily  # noqa: E402
from placebo.selection import (  # noqa: E402
    CoverageMap,
    build_coverage_map,
    parse_coverage_json,
)

COMMIT = "0" * 40
TESTS = {"test_add", "test_sub"}


def fault_at(line: int, path: str = "pkg/m.py") -> Mutant:
    return Mutant(
        file=path,
        qualname="m.f",
        operator=OperatorFamily.ARITHMETIC,
        lineno=line,
        col=0,
        span_start=0,
        span_end=1,
        original="+",
        replacement="-",
        subject_commit=COMMIT,
    )


# The observed output format: line numbers are strings, contexts carry a
# "|run" suffix, and import-time lines are attributed to the empty context.
PAYLOAD = {
    "files": {
        "pkg/m.py": {
            "contexts": {
                "1": [""],
                "2": ["tests/test_m.py::test_add|run"],
                "4": [""],
                "5": ["tests/test_m.py::test_sub|run"],
                "6": ["tests/test_m.py::test_add|run",
                      "tests/test_m.py::test_sub|run"],
            }
        }
    }
}


# -- parsing ---------------------------------------------------------------


def test_parses_the_real_coverage_format():
    cmap = parse_coverage_json(PAYLOAD, TESTS)
    assert cmap.lines["pkg/m.py"][2] == {"test_add"}
    assert cmap.lines["pkg/m.py"][6] == {"test_add", "test_sub"}
    assert cmap.lines["pkg/m.py"][1] == set(), "import-time lines name no test"


def test_windows_paths_are_normalised():
    """Mutant ids address files with forward slashes, so a backslash key would
    match nothing and selection would silently never narrow."""
    payload = {"files": {"pkg\\m.py": {"contexts": {"2": ["t.py::test_add|run"]}}}}
    cmap = parse_coverage_json(payload, TESTS)
    assert "pkg/m.py" in cmap.lines
    assert cmap.tests_for(fault_at(2)) == {"test_add"}


def test_contexts_for_unknown_tests_are_ignored():
    """A context naming a test that is not in the patch is not evidence about
    the patch."""
    payload = {"files": {"pkg/m.py": {"contexts": {"2": ["t.py::test_stranger|run"]}}}}
    cmap = parse_coverage_json(payload, TESTS)
    assert cmap.lines["pkg/m.py"][2] == set()


def test_files_with_no_contexts_are_skipped():
    cmap = parse_coverage_json({"files": {"pkg/empty.py": {"contexts": {}}}}, TESTS)
    assert cmap.lines == {}


def test_missing_files_key_is_tolerated():
    assert parse_coverage_json({}, TESTS).lines == {}


# -- selection must be conservative ----------------------------------------


def test_an_attributed_line_selects_only_its_tests():
    """The whole point: this is where time is saved."""
    cmap = parse_coverage_json(PAYLOAD, TESTS)
    assert cmap.tests_for(fault_at(2)) == {"test_add"}
    assert cmap.tests_for(fault_at(5)) == {"test_sub"}


def test_an_import_time_line_selects_every_test():
    """coverage attributes import-time execution to no test. Treating that as
    'no test reaches it' would drop a whole class of faults, since a def line
    or a module constant affects every test that imports the module."""
    cmap = parse_coverage_json(PAYLOAD, TESTS)
    assert cmap.tests_for(fault_at(1)) == TESTS


def test_a_line_absent_from_the_map_selects_every_test():
    cmap = parse_coverage_json(PAYLOAD, TESTS)
    assert cmap.tests_for(fault_at(99)) == TESTS


def test_a_file_absent_from_the_map_selects_every_test():
    cmap = parse_coverage_json(PAYLOAD, TESTS)
    assert cmap.tests_for(fault_at(2, path="pkg/other.py")) == TESTS


def test_an_incomplete_map_selects_every_test():
    """If instrumentation failed, narrowing would be guessing."""
    cmap = CoverageMap(all_tests=TESTS, complete=False)
    cmap.lines = {"pkg/m.py": {2: {"test_add"}}}
    assert cmap.tests_for(fault_at(2)) == TESTS


def test_a_map_with_no_tests_selects_nothing_rather_than_crashing():
    assert CoverageMap(all_tests=set()).tests_for(fault_at(2)) == set()


# -- reported savings ------------------------------------------------------


def test_reduction_reports_the_share_of_executions_avoided():
    cmap = parse_coverage_json(PAYLOAD, TESTS)
    # Lines 2 and 5 select one test each; line 1 selects both.
    faults = [fault_at(2), fault_at(5), fault_at(1)]
    # 1 + 1 + 2 = 4 selected, against 3 x 2 = 6 exhaustive.
    assert cmap.reduction(faults) == round(1 - 4 / 6, 4)


def test_reduction_is_zero_when_nothing_can_be_narrowed():
    cmap = parse_coverage_json(PAYLOAD, TESTS)
    assert cmap.reduction([fault_at(1), fault_at(99)]) == 0.0


def test_reduction_of_an_empty_corpus_is_zero():
    assert parse_coverage_json(PAYLOAD, TESTS).reduction([]) == 0.0


def test_map_summary_is_serialisable():
    import json

    payload = parse_coverage_json(PAYLOAD, TESTS).to_dict()
    json.dumps(payload)
    assert payload["tests"] == 2
    assert payload["attributed_lines"] == 3, "lines 2, 5 and 6 name a test"


# -- building the map ------------------------------------------------------


def test_building_without_tests_or_packages_is_incomplete():
    """Both are required to instrument anything, and an incomplete map is the
    honest answer rather than an empty one that would exclude everything."""
    assert not build_coverage_map(None, "t.py", "", set(), ["pkg"]).complete
    assert not build_coverage_map(None, "t.py", "", TESTS, []).complete


def test_building_falls_back_to_the_full_suite_when_instrumentation_fails():
    class BrokenRunner:
        workspace = ROOT

        def extra_tests(self, files):
            raise OSError("cannot stage tests")

    cmap = build_coverage_map(BrokenRunner(), "t.py", "code", TESTS, ["pkg"])
    assert not cmap.complete
    assert cmap.tests_for(fault_at(2)) == TESTS

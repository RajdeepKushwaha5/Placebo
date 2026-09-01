"""Tests for unified-diff parsing and pull-request scoping.

The load-bearing detail is line accounting. A removed line occupies no
position on the new side, so counting it would shift every line number after
the first deletion. That failure is silent: the audit still runs, still prints
verdicts, and scopes them against the wrong code. Several tests below exist
only to pin that.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.diff import (  # noqa: E402
    changed_test_functions,
    extract_tests,
    parse_unified_diff,
    scope_faults,
)
from placebo.mutation.models import Mutant, OperatorFamily  # noqa: E402

COMMIT = "0" * 40


def fault_at(path: str, line: int) -> Mutant:
    return Mutant(
        file=path, qualname=f"f{line}", operator=OperatorFamily.ARITHMETIC,
        lineno=line, col=0, span_start=line, span_end=line + 1,
        original="+", replacement="-", subject_commit=COMMIT,
    )


SIMPLE = textwrap.dedent("""\
    diff --git a/pkg/m.py b/pkg/m.py
    index 1111111..2222222 100644
    --- a/pkg/m.py
    +++ b/pkg/m.py
    @@ -1,3 +1,4 @@
     def add(a, b):
    -    return a + b
    +    result = a + b
    +    return result

    """)


# -- parsing ---------------------------------------------------------------


def test_parses_added_lines_with_correct_numbers():
    diff = parse_unified_diff(SIMPLE)
    assert diff.paths == ["pkg/m.py"]
    # Line 1 is context; the two added lines are 2 and 3.
    assert diff.files["pkg/m.py"].added_lines == {2, 3}


def test_removed_lines_do_not_advance_the_new_side_counter():
    """The bug this guards: counting a removed line shifts every subsequent
    line number, so the scope silently points at the wrong code."""
    diff = parse_unified_diff(textwrap.dedent("""\
        --- a/pkg/m.py
        +++ b/pkg/m.py
        @@ -1,5 +1,4 @@
         line_one
        -removed_a
        -removed_b
         line_four
        +added_here
        """))
    # After one context line and two deletions, the next context line is
    # still new-side line 2, so the addition lands on line 3.
    assert diff.files["pkg/m.py"].added_lines == {3}


def test_multiple_hunks_reset_the_counter():
    diff = parse_unified_diff(textwrap.dedent("""\
        --- a/pkg/m.py
        +++ b/pkg/m.py
        @@ -1,2 +1,3 @@
         a
        +b
        @@ -50,2 +51,3 @@
         c
        +d
        """))
    assert diff.files["pkg/m.py"].added_lines == {2, 52}


def test_hunk_header_without_a_line_count_is_handled():
    diff = parse_unified_diff("--- a/m.py\n+++ b/m.py\n@@ -1 +1 @@\n+x\n")
    assert diff.files["m.py"].added_lines == {1}


def test_a_new_file_is_marked():
    diff = parse_unified_diff(textwrap.dedent("""\
        --- /dev/null
        +++ b/pkg/new.py
        @@ -0,0 +1,2 @@
        +import os
        +x = 1
        """))
    change = diff.files["pkg/new.py"]
    assert change.is_new_file and change.added_lines == {1, 2}


def test_a_deleted_file_records_no_added_lines():
    diff = parse_unified_diff(textwrap.dedent("""\
        --- a/pkg/gone.py
        +++ /dev/null
        @@ -1,2 +0,0 @@
        -x = 1
        -y = 2
        """))
    change = diff.files["pkg/gone.py"]
    assert change.is_deleted and change.added_lines == set()


def test_multiple_files_are_separated():
    diff = parse_unified_diff(SIMPLE + textwrap.dedent("""\
        --- a/tests/test_m.py
        +++ b/tests/test_m.py
        @@ -1,1 +1,2 @@
         import pkg
        +def test_new(): pass
        """))
    assert diff.paths == ["pkg/m.py", "tests/test_m.py"]
    assert diff.files["tests/test_m.py"].added_lines == {2}


def test_empty_and_unrecognised_input_yields_no_files():
    assert parse_unified_diff("").paths == []
    assert parse_unified_diff("not a diff at all\njust text\n").paths == []


def test_summary_is_serialisable():
    import json

    payload = parse_unified_diff(SIMPLE).to_dict()
    json.dumps(payload)
    assert payload["files"] == 1 and payload["added_lines"] == 2


# -- classifying paths -----------------------------------------------------


def test_test_files_are_separated_from_source_files():
    diff = parse_unified_diff(SIMPLE + textwrap.dedent("""\
        --- a/tests/test_m.py
        +++ b/tests/test_m.py
        @@ -1,1 +1,2 @@
         import pkg
        +x = 1
        """))
    assert diff.test_paths() == ["tests/test_m.py"]
    assert diff.source_paths() == ["pkg/m.py"]


def test_a_test_file_outside_the_test_root_is_still_recognised():
    """Many projects keep tests beside the code they exercise."""
    diff = parse_unified_diff(textwrap.dedent("""\
        --- a/pkg/test_inline.py
        +++ b/pkg/test_inline.py
        @@ -1,1 +1,2 @@
         import pkg
        +x = 1
        """))
    assert diff.test_paths() == ["pkg/test_inline.py"]
    assert diff.source_paths() == []


def test_non_python_files_are_not_source_paths():
    diff = parse_unified_diff(textwrap.dedent("""\
        --- a/README.md
        +++ b/README.md
        @@ -1,1 +1,2 @@
         title
        +new line
        """))
    assert diff.source_paths() == []


# -- finding the changed tests ---------------------------------------------


def _write_suite(tmp_path: Path) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_m.py").write_text(textwrap.dedent("""\
        import pytest

        from pkg.m import add


        def test_untouched():
            assert add(1, 1) == 2


        def test_changed():
            assert add(2, 2) == 4


        @pytest.mark.parametrize("n", [1, 2])
        def test_decorated(n):
            assert add(n, 0) == n
        """), encoding="utf-8")
    return tmp_path


def test_only_tests_the_diff_touched_are_selected(tmp_path):
    repo = _write_suite(tmp_path)
    # Line 11 is inside test_changed.
    diff = parse_unified_diff(
        "--- a/tests/test_m.py\n+++ b/tests/test_m.py\n@@ -11,1 +11,1 @@\n+    assert add(2, 2) == 4\n"
    )
    assert changed_test_functions(diff, repo) == {"tests/test_m.py": ["test_changed"]}


def test_a_touched_decorated_test_is_selected(tmp_path):
    repo = _write_suite(tmp_path)
    diff = parse_unified_diff(
        "--- a/tests/test_m.py\n+++ b/tests/test_m.py\n@@ -16,1 +16,1 @@\n+    assert add(n, 0) == n\n"
    )
    assert changed_test_functions(diff, repo) == {"tests/test_m.py": ["test_decorated"]}


def test_a_missing_or_unparseable_file_is_skipped(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_broken.py").write_text("def (((\n", encoding="utf-8")
    diff = parse_unified_diff(
        "--- a/tests/test_broken.py\n+++ b/tests/test_broken.py\n@@ -1,1 +1,1 @@\n+x\n"
        "--- a/tests/test_absent.py\n+++ b/tests/test_absent.py\n@@ -1,1 +1,1 @@\n+x\n"
    )
    assert changed_test_functions(diff, tmp_path) == {}


# -- building the patch ----------------------------------------------------


def test_extracted_patch_is_valid_python_carrying_its_imports(tmp_path):
    import ast

    repo = _write_suite(tmp_path)
    code = extract_tests(repo, {"tests/test_m.py": ["test_changed"]})
    ast.parse(code)
    assert "from pkg.m import add" in code
    assert "import pytest" in code
    assert "def test_changed" in code
    assert "def test_untouched" not in code


def test_extraction_keeps_decorators(tmp_path):
    """Dropping a parametrize decorator would change what the test asserts."""
    repo = _write_suite(tmp_path)
    code = extract_tests(repo, {"tests/test_m.py": ["test_decorated"]})
    assert "@pytest.mark.parametrize" in code


def test_extracting_nothing_returns_an_empty_patch(tmp_path):
    repo = _write_suite(tmp_path)
    assert extract_tests(repo, {"tests/test_m.py": ["test_absent"]}) == ""


def test_imports_are_not_duplicated_across_files(tmp_path):
    repo = _write_suite(tmp_path)
    (repo / "tests" / "test_other.py").write_text(
        "import pytest\n\n\ndef test_other():\n    assert True\n", encoding="utf-8")
    code = extract_tests(repo, {"tests/test_m.py": ["test_changed"],
                                "tests/test_other.py": ["test_other"]})
    assert code.count("import pytest") == 1
    assert "def test_changed" in code and "def test_other" in code


# -- scoping the fault corpus ----------------------------------------------


def test_scope_keeps_only_faults_on_touched_source_lines():
    diff = parse_unified_diff(SIMPLE)  # touches pkg/m.py lines 2 and 3
    faults = [fault_at("pkg/m.py", 2), fault_at("pkg/m.py", 9),
              fault_at("pkg/other.py", 2)]
    assert [f.lineno for f in scope_faults(faults, diff)] == [2]


def test_a_test_only_diff_keeps_the_whole_corpus():
    """Otherwise every test would be UNPROVEN against an empty corpus, which
    reads like a verdict but is an artifact of the scope."""
    diff = parse_unified_diff(textwrap.dedent("""\
        --- a/tests/test_m.py
        +++ b/tests/test_m.py
        @@ -1,1 +1,2 @@
         import pkg
        +def test_new(): pass
        """))
    faults = [fault_at("pkg/m.py", 2), fault_at("pkg/m.py", 9)]
    assert scope_faults(faults, diff) == faults


def test_a_changed_file_with_no_fault_on_a_touched_line_falls_back_to_the_file():
    diff = parse_unified_diff(SIMPLE)
    faults = [fault_at("pkg/m.py", 40), fault_at("pkg/other.py", 1)]
    scoped = scope_faults(faults, diff)
    assert [f.file for f in scoped] == ["pkg/m.py"]


def test_scope_never_returns_an_empty_corpus():
    diff = parse_unified_diff(SIMPLE)
    faults = [fault_at("pkg/unrelated.py", 1)]
    assert scope_faults(faults, diff) == faults

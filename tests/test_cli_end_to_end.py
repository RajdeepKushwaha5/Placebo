"""End-to-end tests for every public CLI command.

The roadmap's engineering gate asks for these because the CLI is the only part
a user actually touches and it had no automated execution at all. Everything
here runs the real command against a real repository built in a temp
directory, including real pytest subprocesses, so a command that crashes on
startup or writes a malformed artifact fails here rather than in front of
someone.

The subject is deliberately tiny and deliberately under-tested: its suite
covers `add` and ignores `clamp`, so a census has something real to find and
the audit has a genuine gap to close.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Per-process so concurrent runs cannot share a workspace or census path.
SUBJECT_NAME = f"clie2e{os.getpid()}"

OPS = textwrap.dedent("""\
    def add(a, b):
        return a + b


    def clamp(value, low, high):
        if value < low:
            return low
        if value > high:
            return high
        return value
    """)

# Covers add, and never calls clamp. The gap is the point.
TESTS = textwrap.dedent("""\
    from calc.ops import add


    def test_add():
        assert add(2, 3) == 5


    def test_add_negative():
        assert add(-1, 1) == 0
    """)

CONFIG = textwrap.dedent(f"""\
    version = 1
    name = "{SUBJECT_NAME}"
    language = "python"
    test_command = ["python", "-m", "pytest", "-q"]
    source_roots = ["calc"]
    test_roots = ["tests"]
    mutation_targets = ["calc/ops.py"]
    import_names = ["calc"]
    timeout_seconds = 60
    """)


def cli(*argv: str) -> tuple[int, str]:
    """Invoke the CLI in-process and capture what a user would see.

    Audits run locally here. These tests are about command behaviour, not the
    execution boundary, and containerising them would make them slow and couple
    two concerns. `tests/test_sandbox.py` covers the boundary itself.
    """
    from placebo.cli import main

    argv = list(argv)
    if argv and argv[0] in ("audit", "audit-pr") and "--unsafe-local" not in argv:
        argv.append("--unsafe-local")

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


@pytest.fixture
def repo(tmp_path):
    """A minimal but genuinely runnable Python repository."""
    (tmp_path / "calc").mkdir()
    (tmp_path / "calc" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "calc" / "ops.py").write_text(OPS, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ops.py").write_text(TESTS, encoding="utf-8")
    (tmp_path / ".placebo.toml").write_text(CONFIG, encoding="utf-8")
    yield tmp_path

    # The census writes into Placebo's own artifacts directory, so a test that
    # produced one must not leave it behind for the consistency checker.
    leftovers = [
        ROOT / "artifacts" / f"census_{SUBJECT_NAME}.json",
        ROOT / "artifacts" / f"survivor_triage_{SUBJECT_NAME}.json",
        *(ROOT / ".placebo-cache").glob(f"{SUBJECT_NAME}.sqlite*"),
    ]
    for leftover in leftovers:
        try:
            leftover.unlink(missing_ok=True)
        except PermissionError:  # pragma: no cover - Windows may still hold a
            pass                 # sqlite WAL file briefly after close


# -- doctor ----------------------------------------------------------------


def test_doctor_accepts_a_well_formed_repository(repo):
    code, out = cli("doctor", str(repo), "--quick")
    assert code == 0
    assert "SUPPORTED" in out


def test_doctor_json_names_the_repository(repo):
    code, out = cli("doctor", str(repo), "--quick", "--json")
    assert code == 0
    assert json.loads(out)["config"]["name"] == SUBJECT_NAME


# -- census ----------------------------------------------------------------


@pytest.mark.slow
def test_census_finds_the_gap_the_suite_leaves(repo):
    """The suite never calls clamp, so faults in clamp must survive."""
    code, out = cli("census", str(repo), "--workers", "2")
    assert code == 0, out
    assert "mutation score" in out

    stored = json.loads(
        (ROOT / "artifacts" / f"census_{SUBJECT_NAME}.json").read_text(encoding="utf-8")
    )
    assert stored, "census wrote no fault map"
    statuses = {run["status"] for run in stored.values()}
    assert "survived" in statuses, "an untested function must leave survivors"


@pytest.mark.slow
def test_gaps_lists_the_survivors_after_a_census(repo):
    assert cli("census", str(repo), "--workers", "2")[0] == 0
    code, out = cli("gaps", "--repo", str(repo))
    assert code == 0
    assert "Undetected" in out
    assert "clamp" in out, "the untested function should appear as a gap"


# -- audit -----------------------------------------------------------------


@pytest.mark.slow
def test_audit_credits_a_test_that_closes_a_real_gap(repo):
    assert cli("census", str(repo), "--workers", "2")[0] == 0

    patch = repo / "candidate.py"
    patch.write_text(textwrap.dedent("""\
        from calc.ops import add, clamp


        def test_clamp_low():
            assert clamp(-5, 0, 10) == 0


        def test_add_again():
            assert add(2, 3) == 5
        """), encoding="utf-8")

    code, out = cli("audit", str(patch), "--repo", str(repo))
    assert code == 0, out
    assert "VALUABLE" in out, "the clamp test closes a gap the suite misses"
    assert "REDUNDANT_WITH_EXISTING" in out, "the add test only repeats the suite"


@pytest.mark.slow
def test_audit_minimize_writes_a_smaller_patch_and_verifies_it(repo):
    assert cli("census", str(repo), "--workers", "2")[0] == 0

    patch = repo / "candidate.py"
    patch.write_text(textwrap.dedent("""\
        from calc.ops import clamp


        def test_clamp_low():
            assert clamp(-5, 0, 10) == 0


        def test_clamp_low_again():
            assert clamp(-1, 0, 10) == 0
        """), encoding="utf-8")

    code, out = cli("audit", str(patch), "--repo", str(repo), "--minimize")
    assert code == 0, out
    assert "NO LOSS (re-executed)" in out, "minimization must be verified, not asserted"
    assert (repo / "candidate.minimized.py").is_file()


def test_audit_refuses_a_missing_patch(repo):
    code, out = cli("audit", str(repo / "absent.py"), "--repo", str(repo))
    assert code == 2
    assert "no such patch" in out


def test_audit_refuses_without_a_census(repo):
    patch = repo / "c.py"
    patch.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    code, out = cli("audit", str(patch), "--repo", str(repo))
    assert code == 2
    assert "census" in out


# -- audit-pr --------------------------------------------------------------


def test_audit_pr_refuses_a_missing_diff(repo):
    code, out = cli("audit-pr", str(repo / "absent.diff"), "--repo", str(repo))
    assert code == 2
    assert "no such diff" in out


def test_audit_pr_reports_when_a_diff_changes_no_test(repo, tmp_path):
    """A source-only pull request needs no test audit, and saying so is a
    better answer than auditing nothing and printing zeros."""
    diff = tmp_path / "src.diff"
    diff.write_text(
        "--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -1,2 +1,3 @@\n def add(a, b):\n+    # note\n     return a + b\n",
        encoding="utf-8",
    )
    code, out = cli("audit-pr", str(diff), "--repo", str(repo))
    assert code == 0
    assert "no test functions added or modified" in out


def test_audit_pr_rejects_input_that_is_not_a_diff(repo, tmp_path):
    junk = tmp_path / "junk.diff"
    junk.write_text("this is not a diff\n", encoding="utf-8")
    code, out = cli("audit-pr", str(junk), "--repo", str(repo))
    assert code == 2
    assert "no recognisable file changes" in out


@pytest.mark.slow
def test_audit_pr_audits_only_the_changed_test(repo, tmp_path):
    assert cli("census", str(repo), "--workers", "2")[0] == 0

    # Add a test to the repository, then describe it with a diff.
    suite = repo / "tests" / "test_ops.py"
    suite.write_text(suite.read_text(encoding="utf-8") + textwrap.dedent("""\


        def test_clamp_high():
            from calc.ops import clamp
            assert clamp(99, 0, 10) == 10
        """), encoding="utf-8")
    added_at = len(suite.read_text(encoding="utf-8").splitlines())

    diff = tmp_path / "pr.diff"
    diff.write_text(
        f"--- a/tests/test_ops.py\n+++ b/tests/test_ops.py\n"
        f"@@ -{added_at},0 +{added_at},1 @@\n+    assert clamp(99, 0, 10) == 10\n",
        encoding="utf-8",
    )

    code, out = cli("audit-pr", str(diff), "--repo", str(repo))
    assert code == 0, out
    assert "test_clamp_high" in out
    assert "test_add" not in out, "untouched tests are not this PR's concern"
    assert "scope:" in out, "the narrowed scope must be stated with the verdicts"


@pytest.mark.slow
def test_audit_pr_reads_a_diff_from_stdin(repo, tmp_path, monkeypatch):
    assert cli("census", str(repo), "--workers", "2")[0] == 0

    suite = repo / "tests" / "test_ops.py"
    suite.write_text(suite.read_text(encoding="utf-8") + textwrap.dedent("""\


        def test_clamp_high():
            from calc.ops import clamp
            assert clamp(99, 0, 10) == 10
        """), encoding="utf-8")
    added_at = len(suite.read_text(encoding="utf-8").splitlines())

    monkeypatch.setattr(sys, "stdin", io.StringIO(
        f"--- a/tests/test_ops.py\n+++ b/tests/test_ops.py\n"
        f"@@ -{added_at},0 +{added_at},1 @@\n+    assert clamp(99, 0, 10) == 10\n"
    ))
    code, out = cli("audit-pr", "-", "--repo", str(repo))
    assert code == 0, out
    assert "stdin" in out


# -- verify ----------------------------------------------------------------


def test_verify_replays_a_committed_bundle():
    """The bundles ship with the repository, so this needs no fixture."""
    code, out = cli("verify", "--bundle", "artifacts/bundle")
    assert code == 0
    assert "claims hold" in out
    assert "BROKEN" not in out


def test_verify_reports_a_missing_bundle(tmp_path):
    code, _out = cli("verify", "--bundle", str(tmp_path / "absent"))
    assert code != 0


# -- explain ---------------------------------------------------------------


def test_explain_names_the_fault_a_test_exists_to_detect():
    code, out = cli("explain", "test_placebo_01")
    assert code == 0
    assert "exists to detect" in out
    assert "verified by" in out


def test_explain_is_honest_about_an_unknown_test():
    code, out = cli("explain", "test_that_was_never_generated")
    assert code != 0 or "no" in out.lower()


# -- structural guards -----------------------------------------------------


def test_no_command_can_return_none():
    """Every command's exit code is checked by callers and by CI.

    A command that falls off the end returns None, which compares unequal to
    every exit code and reads as a crash nobody caused. This happened: a patch
    inserted two module-level helpers into the middle of the audit body, so
    everything after them became unreachable and the audit returned None while
    still printing a plausible-looking header.
    """
    import ast

    source = (ROOT / "src" / "placebo" / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    commands = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and (node.name.startswith("cmd_") or node.name in ("_run_audit",
                                                           "_audit_and_report"))
    ]
    assert commands, "no command functions found"

    for node in commands:
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        assert returns, f"{node.name} returns nothing"
        assert any(r.value is not None for r in returns), \
            f"{node.name} never returns a value"


def test_no_unreachable_code_follows_a_return():
    """The shape of the bug above: statements after a return in the same block.

    Python accepts it silently, and the function simply stops doing what it
    looks like it does.
    """
    import ast

    source = (ROOT / "src" / "placebo" / "cli.py").read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(source)):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body[:-1]):
            if isinstance(statement, (ast.Return, ast.Raise)):
                following = body[index + 1]
                offenders.append(
                    f"{type(node).__name__} line {statement.lineno}: "
                    f"{type(following).__name__} at {following.lineno} is unreachable"
                )
    assert not offenders, "unreachable code:\n  " + "\n  ".join(offenders)


def test_every_documented_command_is_reachable_from_the_parser():
    from placebo.cli import build_parser

    choices = build_parser()._subparsers._group_actions[0].choices
    for command in ("audit", "audit-pr", "gaps", "census", "explain",
                    "verify", "doctor"):
        assert command in choices
        assert choices[command].get_default("func") is not None, \
            f"{command} has no handler"

"""Deterministic, model-free suite repair.

Fairness control. A developer who asks an assistant for tests does not merge
them blindly: they run the suite once and delete whatever is red against
correct code. Giving the baseline that same courtesy is the difference between
a fair comparison and a strawman.

This repair uses no model. It runs each test once on clean HEAD and keeps the
ones that pass, so it is available identically to every condition.
"""

from __future__ import annotations

import ast
import re

from ..verification.runner import SubjectRunner

_PROBE_PATH = "tests/test_placebo_repair_probe.py"


def split_tests(suite_code: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a suite file into (preamble, [(test_name, test_source), ...])."""
    try:
        tree = ast.parse(suite_code)
    except SyntaxError:
        return (suite_code, [])

    lines = suite_code.splitlines(keepends=True)
    starts: list[int] = []
    running = 0
    for line in lines:
        starts.append(running)
        running += len(line)
    starts.append(running)

    def block_start(node) -> int:
        """First line of the test, including decorators and the comment block.

        The `# fault detected:` / `# mutant id:` annotations above each test are
        the evidence that makes the patch the evidence a reviewer reads, and the bundle builder
        reads them back. Starting at the `def` line would silently discard them.
        """
        line = node.lineno - 1
        if node.decorator_list:
            line = min(line, node.decorator_list[0].lineno - 1)
        while line > 0:
            previous = lines[line - 1].strip()
            if previous.startswith("#"):
                line -= 1
            else:
                break
        return line

    tests: list[tuple[str, str]] = []
    first_test_line = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            begin_line = block_start(node)
            if first_test_line is None:
                first_test_line = begin_line
            begin = starts[begin_line]
            end = starts[min(node.end_lineno, len(lines))]
            tests.append((node.name, suite_code[begin:end]))

    preamble = suite_code[: starts[first_test_line]] if first_test_line is not None else suite_code
    return (preamble, tests)


def keep_green_tests(
    runner: SubjectRunner, suite_code: str
) -> tuple[str, list[str], list[str]]:
    """Return (repaired_suite, kept_names, dropped_names).

    A test is kept only if it passes against correct code on its own.
    """
    preamble, tests = split_tests(suite_code)
    if not tests:
        # A non-empty file with no extractable tests is not a repaired suite.
        # Returning it unchanged used to make malformed baseline candidates
        # appear retained even though the final suite was red on clean HEAD.
        dropped = ["<unparseable_or_no_tests>"] if suite_code.strip() else []
        return ("", [], dropped)

    kept: list[tuple[str, str]] = []
    dropped: list[str] = []
    for name, source in tests:
        probe = preamble + "\n" + source
        with runner.extra_tests({_PROBE_PATH: probe}):
            result = runner.run_suite([_PROBE_PATH])
        if result.passed:
            kept.append((name, source))
        else:
            dropped.append(name)

    if not kept:
        return ("", [], dropped)
    repaired = preamble + "\n" + "\n\n".join(src for _, src in kept)
    return (repaired, [n for n, _ in kept], dropped)


def count_tests(suite_code: str) -> int:
    try:
        tree = ast.parse(suite_code)
    except SyntaxError:
        return 0
    return sum(
        1 for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )

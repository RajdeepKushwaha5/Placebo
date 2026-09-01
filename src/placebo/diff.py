"""Unified-diff parsing, for auditing a pull request rather than a whole repo.

Two questions are answered here, and they are different questions:

    which tests did this change add or touch?   -> what to audit
    which source lines did this change touch?   -> what to audit it against

Auditing a whole repository is the right default for a one-off report and the
wrong default for a pull request, where the reviewer is deciding about *this
diff*. Scoping the fault corpus to the code the diff touches is also what makes
a PR audit fast enough to run per push.

Scope is a reporting decision, not a correctness one
----------------------------------------------------
Narrowing the corpus changes what "novel" is measured against, so the narrowed
scope is always reported alongside the verdicts rather than left implicit. A
test that looks UNPROVEN against 12 faults from one file may well be valuable
against the repository's full corpus, and the output has to say which question
it answered.

Only the parts of the format that carry meaning are parsed: file headers and
hunk headers. Diffs are produced by many tools with many options, so anything
unrecognised is skipped rather than treated as an error.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

# "+++ b/pkg/module.py" and "--- a/pkg/module.py", with optional timestamps.
_NEW_FILE = re.compile(r"^\+\+\+\s+(?:b/)?(\S+)")
_OLD_FILE = re.compile(r"^---\s+(?:a/)?(\S+)")
# "@@ -12,7 +12,9 @@" - only the new-side range matters for added code.
_HUNK = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")

_DEV_NULL = "/dev/null"


@dataclass
class FileChange:
    """The new-side lines a diff touches in one file."""

    path: str
    added_lines: set[int] = field(default_factory=set)
    is_new_file: bool = False
    is_deleted: bool = False

    def touches(self, line: int) -> bool:
        return line in self.added_lines


@dataclass
class Diff:
    """A parsed unified diff."""

    files: dict[str, FileChange] = field(default_factory=dict)

    @property
    def paths(self) -> list[str]:
        return sorted(self.files)

    def test_paths(self, test_roots: tuple[str, ...] = ("tests",)) -> list[str]:
        """Changed files that live under a declared test root."""
        roots = tuple(r.rstrip("/") + "/" for r in test_roots)
        return [p for p in self.paths
                if p.startswith(roots) or Path(p).name.startswith("test_")]

    def source_paths(self, test_roots: tuple[str, ...] = ("tests",)) -> list[str]:
        tests = set(self.test_paths(test_roots))
        return [p for p in self.paths if p not in tests and p.endswith(".py")]

    def touches(self, path: str, line: int) -> bool:
        change = self.files.get(path)
        return bool(change and change.touches(line))

    def to_dict(self) -> dict:
        return {
            "files": len(self.files),
            "added_lines": sum(len(f.added_lines) for f in self.files.values()),
            "paths": self.paths,
        }


def parse_unified_diff(text: str) -> Diff:
    """Parse a unified diff into per-file added-line sets.

    Only added and context lines advance the new-side counter; removed lines do
    not exist on the new side. Getting that wrong would shift every line number
    after the first deletion, which is the classic bug in hand-rolled diff
    parsers and would silently mis-scope every audit.
    """
    diff = Diff()
    current: FileChange | None = None
    new_line = 0
    old_path: str | None = None

    for raw in text.splitlines():
        old_match = _OLD_FILE.match(raw)
        if old_match:
            old_path = old_match.group(1)
            continue

        new_match = _NEW_FILE.match(raw)
        if new_match:
            path = new_match.group(1)
            if path == _DEV_NULL:
                # File deleted: record it under its old name and add nothing.
                if old_path and old_path != _DEV_NULL:
                    diff.files.setdefault(
                        old_path, FileChange(path=old_path)
                    ).is_deleted = True
                current = None
            else:
                current = diff.files.setdefault(path, FileChange(path=path))
                current.is_new_file = old_path == _DEV_NULL
            old_path = None
            continue

        if current is None:
            continue

        hunk = _HUNK.match(raw)
        if hunk:
            new_line = int(hunk.group(1))
            continue

        if not raw:
            new_line += 1
        elif raw.startswith("+"):
            current.added_lines.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            pass  # removed lines occupy no position on the new side
        elif raw.startswith(("\\", "diff ", "index ", "similarity ",
                             "rename ", "new file", "deleted file")):
            continue
        else:
            new_line += 1  # context line

    return diff


def changed_test_functions(diff: Diff, repo: Path,
                           test_roots: tuple[str, ...] = ("tests",)) -> dict[str, list[str]]:
    """Test functions whose body a diff added or modified.

    Maps a test file path to the names of its changed tests. A test is included
    when any added line falls inside its definition, so both a new test and a
    one-line edit to an existing one are caught.
    """
    found: dict[str, list[str]] = {}
    for relative in diff.test_paths(test_roots):
        path = repo / relative
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        change = diff.files[relative]
        names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            and any(
                node.lineno <= line <= (node.end_lineno or node.lineno)
                for line in change.added_lines
            )
        ]
        if names:
            found[relative] = sorted(names)
    return found


def extract_tests(repo: Path, selections: dict[str, list[str]]) -> str:
    """Build one auditable patch from the named tests across changed files.

    Imports are collected from every source file so the extracted tests still
    resolve their fixtures and helpers, and duplicate imports are dropped.
    """
    imports: list[str] = []
    seen_imports: set[str] = set()
    bodies: list[str] = []

    for relative in sorted(selections):
        path = repo / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                text = "\n".join(lines[node.lineno - 1: node.end_lineno])
                if text not in seen_imports:
                    seen_imports.add(text)
                    imports.append(text)

        wanted = set(selections[relative])
        for node in tree.body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in wanted):
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                bodies.append("\n".join(lines[start - 1: node.end_lineno]))

    if not bodies:
        return ""
    return "\n".join(imports) + "\n\n\n" + "\n\n\n".join(bodies) + "\n"


def scope_faults(faults: list, diff: Diff,
                 test_roots: tuple[str, ...] = ("tests",)) -> list:
    """Faults living in source lines the diff touched.

    Returns the full list when the diff touches no source file, because a
    test-only pull request should still be audited against something. An empty
    corpus would report every test as UNPROVEN, which reads as a verdict but is
    an artifact of the scope.
    """
    changed = set(diff.source_paths(test_roots))
    if not changed:
        return list(faults)
    scoped = [
        f for f in faults
        if f.file in changed and diff.touches(f.file, f.lineno)
    ]
    # A source file may be changed in ways that produce no fault on an added
    # line, in which case fall back to every fault in the changed files.
    if not scoped:
        scoped = [f for f in faults if f.file in changed]
    return scoped or list(faults)

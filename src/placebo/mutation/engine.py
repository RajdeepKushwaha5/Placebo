"""Deterministic AST mutation engine.

Why we ship our own engine instead of using mutmut/cosmic-ray:

* mutmut requires ``os.fork()``, which does not exist on Windows. Standardising
  on Docker purely to get a mutation tool would raise the bar for judges
  reproducing this project from a clean clone.
* We need *stable, content-derived* mutant identities to freeze a
  discovery/held-out split. Both upstream tools address mutants by session
  ordering, which is not reproducible across runs.
* We need surgical single-token edits so the mutant diff shown to the agent is
  one line, not a whole file reformatted by ``ast.unparse``.

The engine walks the AST to find mutation *sites*, then uses ``tokenize`` to
locate the exact source span of the operator token, so every mutant is a
minimal textual substitution.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path

from .models import Mutant, OperatorFamily

# --------------------------------------------------------------------------
# Bounded operator tables (design doc section 12.2)
# --------------------------------------------------------------------------

COMPARISON_SWAPS: dict[str, str] = {
    "<": "<=",
    "<=": "<",
    ">": ">=",
    ">=": ">",
}

EQUALITY_SWAPS: dict[str, str] = {
    "==": "!=",
    "!=": "==",
}

BOOLEAN_SWAPS: dict[str, str] = {
    "and": "or",
    "or": "and",
}

ARITHMETIC_SWAPS: dict[str, str] = {
    "+": "-",
    "-": "+",
    "*": "//",
    "//": "*",
    "%": "*",
}

_COMPARE_OP_SRC: dict[type, str] = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
    ast.NotEq: "!=",
}

_BINOP_SRC: dict[type, str] = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.FloorDiv: "//",
    ast.Mod: "%",
}


@dataclass(frozen=True)
class _Token:
    string: str
    start: int
    end: int
    type: int


class _SourceIndex:
    """Maps AST positions to absolute character offsets in the decoded source.

    ``col_offset`` from the ``ast`` module is a UTF-8 *byte* offset, so it is
    converted through the encoded line prefix rather than used directly.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self.lines = source.splitlines(keepends=True)
        self.line_starts: list[int] = []
        running = 0
        for line in self.lines:
            self.line_starts.append(running)
            running += len(line)
        self.tokens = self._tokenize(source)

    def offset(self, lineno: int, col: int) -> int:
        """Convert a 1-based line / byte column to an absolute char offset."""
        line = self.lines[lineno - 1]
        prefix = line.encode("utf-8")[:col].decode("utf-8", errors="ignore")
        return self.line_starts[lineno - 1] + len(prefix)

    def node_span(self, node: ast.AST) -> tuple[int, int]:
        return (
            self.offset(node.lineno, node.col_offset),
            self.offset(node.end_lineno, node.end_col_offset),
        )

    def _tokenize(self, source: str) -> list[_Token]:
        out: list[_Token] = []
        try:
            raw = tokenize.generate_tokens(io.StringIO(source).readline)
            for tok in raw:
                if tok.type not in (tokenize.OP, tokenize.NAME):
                    continue
                out.append(
                    _Token(
                        string=tok.string,
                        start=self.offset(tok.start[0], tok.start[1]),
                        end=self.offset(tok.end[0], tok.end[1]),
                        type=tok.type,
                    )
                )
        except (tokenize.TokenError, IndentationError):
            # A file we cannot tokenise simply yields no operator-token mutants.
            return []
        return out

    def find_token(
        self, after: int, before: int, wanted: str
    ) -> tuple[int, int] | None:
        """Locate the first `wanted` token strictly inside (after, before)."""
        for tok in self.tokens:
            if tok.start >= after and tok.end <= before and tok.string == wanted:
                return (tok.start, tok.end)
        return None


class _MutationCollector(ast.NodeVisitor):
    """Walks the AST recording every mutation site in the bounded operator set."""

    def __init__(
        self,
        index: _SourceIndex,
        relpath: str,
        commit: str,
        excluded: set[int] | None = None,
    ) -> None:
        self.index = index
        self.relpath = relpath
        self.commit = commit
        self.scope: list[str] = []
        self.mutants: list[Mutant] = []
        self._docstrings: set[int] = set()
        # Node ids living inside type annotations, which are not runtime
        # behavior and whose mutants are equivalent or invalid by construction.
        self._excluded: set[int] = excluded or set()

    # -- scope tracking ----------------------------------------------------

    @property
    def qualname(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

    def _enter(self, node) -> None:
        first = node.body[0] if getattr(node, "body", None) else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            self._docstrings.add(id(first.value))

    def visit_Module(self, node: ast.Module):
        self._enter(node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        self._enter(node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._enter(node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    # -- helpers -----------------------------------------------------------

    def _add(
        self,
        span: tuple[int, int],
        replacement: str,
        family: OperatorFamily,
        node: ast.AST,
    ) -> None:
        original = self.index.source[span[0] : span[1]]
        if original == replacement:
            return
        if id(node) in self._excluded:
            return
        # Module-level statements are type aliases and constants in this
        # subject; mutating them yields import-time noise, not behavior.
        if not self.scope:
            return
        self.mutants.append(
            Mutant(
                file=self.relpath,
                qualname=self.qualname,
                operator=family,
                lineno=node.lineno,
                col=node.col_offset,
                span_start=span[0],
                span_end=span[1],
                original=original,
                replacement=replacement,
                subject_commit=self.commit,
            )
        )

    # -- operators ---------------------------------------------------------

    def visit_Compare(self, node: ast.Compare):
        left_end = self.index.node_span(node.left)[1]
        for op, comparator in zip(node.ops, node.comparators):
            src = _COMPARE_OP_SRC.get(type(op))
            right_start = self.index.node_span(comparator)[0]
            if src:
                span = self.index.find_token(left_end, right_start, src)
                if span:
                    if src in COMPARISON_SWAPS:
                        self._add(span, COMPARISON_SWAPS[src], OperatorFamily.COMPARISON_BOUNDARY, node)
                    elif src in EQUALITY_SWAPS:
                        self._add(span, EQUALITY_SWAPS[src], OperatorFamily.EQUALITY, node)
            left_end = self.index.node_span(comparator)[1]
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp):
        src = "and" if isinstance(node.op, ast.And) else "or"
        left_end = self.index.node_span(node.values[0])[1]
        right_start = self.index.node_span(node.values[1])[0]
        span = self.index.find_token(left_end, right_start, src)
        if span:
            self._add(span, BOOLEAN_SWAPS[src], OperatorFamily.BOOLEAN_LOGIC, node)
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            operand_start = self.index.node_span(node.operand)[0]
            node_start = self.index.node_span(node)[0]
            span = self.index.find_token(node_start, operand_start, "not")
            if span:
                # Drop `not ` including the trailing whitespace run.
                end = span[1]
                while end < len(self.index.source) and self.index.source[end] == " ":
                    end += 1
                self._add((span[0], end), "", OperatorFamily.NEGATION, node)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        src = _BINOP_SRC.get(type(node.op))
        if src and src in ARITHMETIC_SWAPS:
            left_end = self.index.node_span(node.left)[1]
            right_start = self.index.node_span(node.right)[0]
            span = self.index.find_token(left_end, right_start, src)
            if span:
                self._add(span, ARITHMETIC_SWAPS[src], OperatorFamily.ARITHMETIC, node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if id(node) in self._docstrings:
            self.generic_visit(node)
            return
        span = self.index.node_span(node)
        value = node.value
        # Numeric and boolean literals only. String-literal mutation on this
        # subject overwhelmingly hits exception messages, which are not
        # behavioural regressions and would inflate the mutant count with
        # cases no reasonable test should be expected to catch.
        if isinstance(value, bool):
            self._add(span, "False" if value else "True", OperatorFamily.CONSTANT, node)
        elif isinstance(value, int):
            self._add(span, str(value + 1), OperatorFamily.CONSTANT, node)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return):
        if node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None
        ):
            span = self.index.node_span(node.value)
            self._add(span, "None", OperatorFamily.RETURN_VALUE, node)
        self.generic_visit(node)


def _annotation_node_ids(tree: ast.AST) -> set[int]:
    """Collect ids of every node living inside a type annotation.

    Annotations are erased at runtime, so mutating them produces equivalent or
    invalid mutants rather than detectable behavioural faults.
    """
    excluded: set[int] = set()

    def mark(node: ast.AST | None) -> None:
        if node is None:
            return
        for sub in ast.walk(node):
            excluded.add(id(sub))

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            mark(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mark(node.returns)
            args = node.args
            for arg in [
                *args.posonlyargs,
                *args.args,
                *args.kwonlyargs,
                args.vararg,
                args.kwarg,
            ]:
                if arg is not None:
                    mark(arg.annotation)
    return excluded


def enumerate_file(path: Path, relpath: str, commit: str) -> list[Mutant]:
    """Enumerate every mutant in one source file, in deterministic order."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    index = _SourceIndex(source)
    collector = _MutationCollector(index, relpath, commit, _annotation_node_ids(tree))
    collector.visit(tree)
    # Sort by position then operator so ordering never depends on walk order.
    return sorted(
        collector.mutants,
        key=lambda m: (m.file, m.span_start, m.operator.value, m.replacement),
    )


def enumerate_subject(
    root: Path, targets: list[str], commit: str
) -> list[Mutant]:
    """Enumerate mutants across the configured target files."""
    mutants: list[Mutant] = []
    for rel in targets:
        path = root / rel
        if not path.exists():
            raise FileNotFoundError(f"Target file not found: {path}")
        mutants.extend(enumerate_file(path, rel, commit))
    return mutants

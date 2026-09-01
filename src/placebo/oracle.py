"""Oracle levels and brittleness policy.

The problem this addresses
--------------------------
Placebo's generated tests take their expected values by executing the current
implementation. That makes them sound regression detectors and says nothing
about correctness: if the code is already wrong, the recorded value is the
wrong answer, and the test locks it in. The project says so in its limitations,
but saying so in prose is weaker than labelling every individual test.

So each test carries the strength of the oracle behind it:

    L1  specification   an external statement of intent: a documented example,
                        a declared invariant, an issue's acceptance criteria
    L2  differential    agreement with an independent implementation or with a
                        previous release
    L3  metamorphic     a relation that must hold between executions, without
                        needing to know either answer
    L4  snapshot        whatever the current implementation happens to do

Only L4 is available without extra input, and L4 is exactly the level that must
never be described as verified correctness.

Classification is conservative in one direction
-----------------------------------------------
A test is promoted above L4 only on positive structural evidence. Guessing
upward would attach a stronger claim than the evidence supports, which is the
one failure this module exists to prevent. Guessing downward only understates.

Brittleness is separate from strength
-------------------------------------
A test can have a perfectly good oracle and still break on an unrelated change.
Exact exception text, `repr` output, wall-clock values and iteration order all
pin things most projects never promised to keep stable. These are reported as
warnings rather than verdicts, because some of them are deliberate: Placebo's
own counterexample search asserts an exception *message* precisely because that
is the only thing distinguishing one real fault, and a policy that banned it
outright would lose that detection.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum


class OracleLevel(int, Enum):
    """How strong the authority behind an expected value is."""

    SPECIFICATION = 1
    DIFFERENTIAL = 2
    METAMORPHIC = 3
    SNAPSHOT = 4

    @property
    def label(self) -> str:
        return {
            OracleLevel.SPECIFICATION: "L1 specification",
            OracleLevel.DIFFERENTIAL: "L2 differential",
            OracleLevel.METAMORPHIC: "L3 metamorphic",
            OracleLevel.SNAPSHOT: "L4 snapshot",
        }[self]

    @property
    def claims_correctness(self) -> bool:
        """Whether this level supports a statement about intended behaviour."""
        return self is not OracleLevel.SNAPSHOT


# Names whose values change between runs or environments.
_UNSTABLE_MODULES = frozenset({
    "time", "datetime", "random", "uuid", "os", "socket", "platform", "tempfile",
})
_UNSTABLE_CALLS = frozenset({
    "now", "today", "utcnow", "time", "monotonic", "perf_counter",
    "uuid1", "uuid4", "getpid", "gethostname", "random", "randint", "choice",
})
# Builtins whose textual form is an implementation detail.
_REPRESENTATION_CALLS = frozenset({"repr", "str", "format", "hex", "id"})
_SERIALISATION = frozenset({"dumps", "dump", "pickle", "marshal"})
# Roots that are never "another implementation": builtins that merely convert a
# value, and the test framework itself. Counting these as a second implementation
# labelled a broken snapshot assertion as a differential oracle.
_NON_IMPLEMENTATION = frozenset({
    "pytest", "unittest", "mock", "assert_", "self",
    "str", "repr", "len", "int", "float", "bool", "list", "dict", "set",
    "tuple", "sorted", "type", "abs", "round", "format", "hex", "id",
})


@dataclass(frozen=True)
class Brittleness:
    """One reason a test may fail without the behaviour it tests changing."""

    kind: str
    detail: str
    line: int

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail, "line": self.line}


@dataclass
class OracleReport:
    """The oracle strength and brittleness of one test."""

    test: str
    level: OracleLevel
    reason: str
    warnings: list[Brittleness]

    @property
    def brittle(self) -> bool:
        return bool(self.warnings)

    def to_dict(self) -> dict:
        return {
            "test": self.test,
            "oracle_level": int(self.level),
            "oracle_label": self.level.label,
            "claims_correctness": self.level.claims_correctness,
            "reason": self.reason,
            "warnings": [w.to_dict() for w in self.warnings],
        }


def _name_of(node: ast.AST) -> str:
    """Dotted name for an attribute or name node, else an empty string."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _root_of(node: ast.AST) -> str:
    dotted = _name_of(node)
    return dotted.split(".")[0] if dotted else ""


def detect_brittleness(func: ast.AST) -> list[Brittleness]:
    """Assertions that pin things a project did not necessarily promise."""
    found: list[Brittleness] = []

    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = _name_of(node.func)
            leaf = name.split(".")[-1] if name else ""
            root = _root_of(node.func)

            if leaf in _UNSTABLE_CALLS and (root in _UNSTABLE_MODULES or not root):
                found.append(Brittleness(
                    "nondeterministic", f"{name}() differs between runs", node.lineno))
            elif leaf in _SERIALISATION:
                found.append(Brittleness(
                    "serialisation",
                    f"{name}() output depends on the serialiser's formatting",
                    node.lineno))
            elif leaf in _REPRESENTATION_CALLS and _in_comparison(node, func):
                found.append(Brittleness(
                    "representation",
                    f"{leaf}() output is a display detail, not a contract",
                    node.lineno))

        # `assert str(excinfo.value) == "..."` pins an exception's wording.
        if isinstance(node, ast.Compare) and _compares_exception_text(node):
            found.append(Brittleness(
                "exception-message",
                "exact exception wording is rarely part of a public contract",
                node.lineno))

    # Deduplicate by (kind, line): one line reports one problem once.
    unique: dict[tuple[str, int], Brittleness] = {}
    for item in found:
        unique.setdefault((item.kind, item.line), item)
    return sorted(unique.values(), key=lambda b: (b.line, b.kind))


def _in_comparison(call: ast.Call, tree: ast.AST) -> bool:
    """True when this call is an operand of a comparison."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            if call is node.left or any(c is call for c in node.comparators):
                return True
    return False


def _compares_exception_text(node: ast.Compare) -> bool:
    operands = [node.left, *node.comparators]
    mentions_exception = any(
        "excinfo" in _name_of(o) or "exception" in _name_of(o).lower()
        or (isinstance(o, ast.Call) and (
            "excinfo" in _name_of(o.func)
            or any("excinfo" in _name_of(a) for a in o.args)))
        for o in operands
    )
    has_literal = any(isinstance(o, ast.Constant) and isinstance(o.value, str)
                      for o in operands)
    return mentions_exception and has_literal


def classify(func: ast.AST, docstring: str | None = None) -> tuple[OracleLevel, str]:
    """Infer the oracle level of one test function.

    Promotion above L4 requires positive evidence, so the default is the
    weakest claim rather than the most flattering one.
    """
    text = (docstring or ast.get_docstring(func) or "").lower() if isinstance(
        func, (ast.FunctionDef, ast.AsyncFunctionDef)) else (docstring or "").lower()

    # L1: the test cites an external authority for what the answer should be.
    for marker in ("per the specification", "documented example", "rfc",
                   "acceptance criteria", "the docs state", "semver.org",
                   "invariant:"):
        if marker in text:
            return OracleLevel.SPECIFICATION, f"cites an external source ({marker})"

    calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
    roots = {_root_of(c.func) for c in calls} - {""}

    # Only the outermost comparison of an assert is the assertion. A nested
    # one is an operand: `assert repr(a < b) == "False"` asserts a recorded
    # string, and reading its inner `<` as the assertion would promote a
    # snapshot to metamorphic, which is the exact overclaim to avoid.
    asserted = [
        node.test for node in ast.walk(func)
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)
    ]

    # L2: two different implementations are compared against each other.
    for compare in asserted:
        operands = [compare.left, *compare.comparators]
        if any(isinstance(o, ast.Constant) for o in operands):
            continue
        call_roots = {
            _root_of(o.func) for o in operands
            if isinstance(o, ast.Call) and _root_of(o.func)
        } - _NON_IMPLEMENTATION
        if len(call_roots) >= 2:
            return (OracleLevel.DIFFERENTIAL,
                    f"compares {' against '.join(sorted(call_roots))}")

    # L3: a relation between executions, with no literal expected value.
    if _is_metamorphic(asserted):
        return (OracleLevel.METAMORPHIC,
                "asserts a relation between executions, not a recorded value")

    if roots:
        return (OracleLevel.SNAPSHOT,
                "expected values record current behaviour of "
                f"{', '.join(sorted(roots))}")
    return OracleLevel.SNAPSHOT, "expected values record current behaviour"


def _is_metamorphic(asserted: list[ast.Compare]) -> bool:
    """An asserted relation between two executions, with no literal expected.

    Takes the already-extracted assert-level comparisons rather than walking,
    so a comparison nested inside a call cannot be mistaken for the assertion.
    """
    for compare in asserted:
        operands = [compare.left, *compare.comparators]
        if any(isinstance(o, ast.Constant) for o in operands):
            continue
        # Every side must execute the subject. `str(x) == pytest.raises(...)`
        # has a call on each side but only one of them runs anything under
        # test, and reading it as a relation would overclaim on broken code.
        if all(_subject_roots(o) for o in operands) and len(operands) >= 2:
            return True
    return False


def _subject_roots(node: ast.AST) -> set[str]:
    """Roots of calls in this expression that are not builtins or the framework."""
    return {
        _root_of(sub.func) for sub in ast.walk(node)
        if isinstance(sub, ast.Call) and _root_of(sub.func)
    } - _NON_IMPLEMENTATION


def report_suite(source: str) -> list[OracleReport]:
    """Label every test in a patch with its oracle level and brittleness."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    reports: list[OracleReport] = []
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")):
            level, reason = classify(node)
            reports.append(OracleReport(
                test=node.name,
                level=level,
                reason=reason,
                warnings=detect_brittleness(node),
            ))
    return sorted(reports, key=lambda r: r.test)


def summarise(reports: list[OracleReport]) -> dict:
    """Counts a reviewer can act on."""
    by_level = {level.label: 0 for level in OracleLevel}
    for report in reports:
        by_level[report.level.label] += 1
    return {
        "tests": len(reports),
        "by_level": by_level,
        "snapshot_only": sum(
            1 for r in reports if r.level is OracleLevel.SNAPSHOT),
        "brittle": sum(1 for r in reports if r.brittle),
        "warnings": sum(len(r.warnings) for r in reports),
    }

"""Finding oracles rather than recording behaviour.

The problem
-----------
Placebo's default oracle is a snapshot: run the input, record what came back.
That detects regressions and says nothing about correctness, because if the
implementation is already wrong the snapshot preserves the wrong answer. Every
test this project generates is labelled L4 for exactly that reason.

The fix is not a better model. It is to stop inventing expected values when the
repository already states them. A docstring example is a claim its authors
made about intended behaviour, in their own words, at a line number anyone can
open. Using it turns an unsourced expected value into a cited one.

Priority
--------
Candidates are produced strongest first, and the level is a property of where
the answer came from rather than of how confident the code feels:

    L1  specification   a documented example or declared invariant, cited
    L2  differential    agreement with another implementation or an older release
    L3  metamorphic     a relation between executions, no answer needed
    L4  snapshot        whatever the code currently does

Only L1 and L3 are sourced here. L2 needs a second implementation or a previous
release to compare against, which is a packaging question rather than a parsing
one, and inventing an approximation of it would be the same mistake as
inventing an expected value.

Honesty
-------
A candidate carries where it came from, so a reviewer can check the source
rather than trust the label. A doctest that no longer matches the
implementation is reported as a conflict rather than silently dropped or
silently trusted: one of the two is wrong, and which one is a human's call.
"""

from __future__ import annotations

import ast
import doctest
import re
from dataclasses import dataclass, field
from pathlib import Path

from .oracle import OracleLevel

# A doctest line that only sets something up, rather than asserting a value.
_ASSIGNMENT = re.compile(r"^\s*\w+\s*=\s*[^=]")


@dataclass(frozen=True)
class OracleCandidate:
    """An expected value, and where the authority for it came from."""

    expression: str
    expected: str
    level: OracleLevel
    source: str
    confidence: str
    setup: tuple[str, ...] = field(default_factory=tuple)

    @property
    def cited(self) -> bool:
        """Whether a human can go and read the authority for this value."""
        return self.level is not OracleLevel.SNAPSHOT and ":" in self.source

    def to_dict(self) -> dict:
        return {
            "expression": self.expression,
            "expected": self.expected,
            "oracle_level": int(self.level),
            "oracle_label": self.level.label,
            "source": self.source,
            "confidence": self.confidence,
            "setup": list(self.setup),
        }

    def render(self) -> str:
        """The assertion, with its provenance attached as a comment.

        The citation is in the generated test rather than only in a report,
        because the person deciding whether to merge is reading the test.
        """
        lines = [
            f"    # Oracle: {self.level.label}",
            f"    # Source: {self.source}",
            f"    # Confidence: {self.confidence}",
        ]
        lines.extend(f"    {line}" for line in self.setup)
        lines.append(f"    assert repr({self.expression}) == {self.expected!r}")
        return "\n".join(lines)


def _locate(lines: list[str], statement: str, estimate: int) -> int:
    """Line number of a doctest statement, found rather than calculated.

    Arithmetic on the docstring's start plus the example's offset is off by one
    whenever a docstring begins its text on the same line as the opening
    quotes. Searching near the estimate is immune to that, and a citation that
    points at the wrong line is worse than no citation at all.
    """
    needle = ">>> " + statement.splitlines()[0].strip()
    for offset in range(0, 6):
        for candidate in (estimate + offset, estimate - offset):
            index = candidate - 1
            if 0 <= index < len(lines) and lines[index].strip() == needle:
                return candidate
    return estimate


def _docstring_line(node) -> int | None:
    """Line the docstring literal starts on.

    `node.lineno` is the `def` or `class` line, several lines above the
    docstring in any real file, so citations built from it point at the wrong
    place. The docstring is the first statement in the body.
    """
    body = getattr(node, "body", None)
    if not body:
        return None
    first = body[0]
    if (isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return first.value.lineno
    return None


def from_docstrings(path: Path, module: str = "") -> list[OracleCandidate]:
    """Documented examples in a source file, as L1 candidates.

    A `>>>` example is the authors stating what their code should do. Parsing
    is delegated to the standard library's doctest parser rather than done by
    hand, so continuation lines, blank-line markers and expected exceptions are
    handled the way Python itself handles them.

    Lines that only bind a name are carried as setup rather than asserted;
    `ver = semver.parse("3.4.5")` states nothing on its own.
    """
    path = Path(path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return []
    lines = source.splitlines()

    parser = doctest.DocTestParser()
    candidates: list[OracleCandidate] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
            continue
        text = ast.get_docstring(node, clean=False)
        if not text or ">>>" not in text:
            continue

        # A citation has to land on the line a reader can open, so the base is
        # where the docstring literal starts, not where `def` is. Using the
        # function's own lineno puts every citation several lines early.
        base = _docstring_line(node)
        if base is None:
            continue

        setup: list[str] = []
        try:
            examples = parser.get_examples(text)
        except ValueError:
            continue

        for example in examples:
            statement = example.source.strip()
            if not statement:
                continue
            expected = example.want.strip()

            if not expected or _ASSIGNMENT.match(statement):
                # Nothing is claimed; keep it so later examples still run.
                setup.append(statement)
                continue
            if statement.startswith(("import ", "from ")):
                setup.append(statement)
                continue
            if "Traceback" in expected:
                # An expected exception is a real claim, but asserting it needs
                # a different shape than a value comparison. Left for later
                # rather than approximated.
                continue

            line = _locate(lines, statement, base + example.lineno)
            candidates.append(OracleCandidate(
                expression=statement,
                expected=expected,
                level=OracleLevel.SPECIFICATION,
                source=f"{path.name}:{line}",
                confidence="contract-backed",
                setup=tuple(setup),
            ))
    return candidates


@dataclass
class SourcingReport:
    """What was found, and how strong it was."""

    candidates: list[OracleCandidate] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def by_level(self) -> dict[str, int]:
        counts = {level.label: 0 for level in OracleLevel}
        for candidate in self.candidates:
            counts[candidate.level.label] += 1
        return counts

    @property
    def strongest(self) -> OracleLevel | None:
        return min((c.level for c in self.candidates), default=None)

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "by_level": self.by_level(),
            "cited": sum(1 for c in self.candidates if c.cited),
            "conflicts": self.conflicts,
        }


def source_oracles(paths: list[Path]) -> SourcingReport:
    """Collect every oracle the repository already states, strongest first."""
    report = SourcingReport()
    for path in paths:
        report.candidates.extend(from_docstrings(path))
    report.candidates.sort(key=lambda c: (int(c.level), c.source))
    return report


def verify_candidates(runner, candidates: list[OracleCandidate],
                      allowed_names: tuple[str, ...] = ()) -> SourcingReport:
    """Check each documented example against the current implementation.

    Three outcomes, and the middle one is the interesting one:

      * agrees          the documentation and the code say the same thing
      * conflicts       they disagree, so one of them is wrong and a human
                        has to decide which. Reported, never silently resolved.
      * unevaluable     the probe could not run it safely

    A conflict is not a failure of this module. Finding one means the
    repository's own documentation contradicts its behaviour, which is worth
    more to a maintainer than any generated test.
    """
    from .verification.prober import extract_expressions, observe

    report = SourcingReport()
    for candidate in candidates:
        safe = extract_expressions(candidate.expression,
                                   allowed_names=allowed_names or None)
        if not safe:
            continue
        observations = observe(runner, None, safe, allowed_names=allowed_names or None)
        for observation in observations:
            if not observation.clean_ok:
                continue
            if _matches(observation.clean_repr, candidate.expected):
                report.candidates.append(candidate)
            else:
                report.conflicts.append({
                    "expression": candidate.expression,
                    "documented": candidate.expected,
                    "actual": observation.clean_repr,
                    "source": candidate.source,
                })
    return report


def _matches(actual: str, documented: str) -> bool:
    """Whether an observed value matches a documented one.

    Compared after normalising whitespace, because a docstring wraps for the
    page width while a repr does not, and treating that as a disagreement
    would report conflicts that are really typography.
    """
    return " ".join(actual.split()) == " ".join(documented.split())

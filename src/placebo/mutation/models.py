"""Data models for mutants and mutation runs.

A mutant is a single, minimal, semantics-changing edit to subject source code.
Identity is content-derived (never enumeration order) so that manifests stay
stable across machines, Python versions and refactors of this package.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path


class OperatorFamily(str, Enum):
    """Bounded operator set (see design doc section 12.2)."""

    COMPARISON_BOUNDARY = "comparison_boundary"
    EQUALITY = "equality"
    BOOLEAN_LOGIC = "boolean_logic"
    NEGATION = "negation"
    CONSTANT = "constant"
    ARITHMETIC = "arithmetic"
    RETURN_VALUE = "return_value"


class MutantStatus(str, Enum):
    """Outcome of running the subject suite against a materialized mutant."""

    KILLED = "killed"           # suite failed -> the fault is detected
    # Candidate sensitivity gap; equivalence and contract relevance need triage.
    SURVIVED = "survived"
    INVALID = "invalid"         # mutant does not import / collect
    TIMEOUT = "timeout"         # exceeded the runtime budget
    ERROR = "error"             # harness failure, excluded from scoring


@dataclass(frozen=True)
class Mutant:
    """One minimal edit, addressed by a stable content hash."""

    file: str                   # subject-relative POSIX path
    qualname: str               # e.g. "Version.compare"
    operator: OperatorFamily
    lineno: int
    col: int
    span_start: int             # absolute char offset into the original file
    span_end: int
    original: str               # exact source text being replaced
    replacement: str            # exact source text substituted in
    subject_commit: str

    @property
    def id(self) -> str:
        """Content-derived identifier. Independent of enumeration order."""
        payload = "|".join(
            [
                self.subject_commit,
                self.file,
                self.qualname,
                self.operator.value,
                str(self.span_start),
                str(self.span_end),
                self.original,
                self.replacement,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def label(self) -> str:
        """Human-readable one-liner used in reports and prompts."""
        return (
            f"{self.file}:{self.lineno} in {self.qualname}: "
            f"`{self.original}` -> `{self.replacement}` ({self.operator.value})"
        )

    def apply(self, source: str) -> str:
        """Return `source` with this single edit applied.

        Verifies the span still matches `original` so a stale manifest fails
        loudly rather than silently producing a different mutant.
        """
        found = source[self.span_start : self.span_end]
        if found != self.original:
            raise ValueError(
                f"Mutant {self.id} span mismatch: expected {self.original!r}, "
                f"found {found!r}. The subject source has changed."
            )
        return source[: self.span_start] + self.replacement + source[self.span_end :]

    def diff_line(self, source: str) -> str:
        """A compact before/after of just the affected line, for prompts."""
        line_start = source.rfind("\n", 0, self.span_start) + 1
        line_end = source.find("\n", self.span_end)
        if line_end == -1:
            line_end = len(source)
        before = source[line_start:line_end]
        after = self.apply(source)[line_start : line_end + len(self.replacement) - len(self.original)]
        return f"- {before.strip()}\n+ {after.strip()}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["operator"] = self.operator.value
        d["id"] = self.id
        d["label"] = self.label
        return d


@dataclass
class MutantRun:
    """Result of executing the subject suite against one mutant."""

    mutant_id: str
    status: MutantStatus
    duration_s: float
    failing_tests: list[str] = field(default_factory=list)
    returncode: int | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


def write_json(path: Path, payload: object) -> None:
    """Deterministic JSON writer: sorted keys, trailing newline, UTF-8."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

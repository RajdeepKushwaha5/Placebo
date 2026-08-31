"""Deterministic candidate admission.

A generated test is *admitted* only when execution proves it does the job.
No model opinion, no heuristic scoring, no self-assessment: every gate below is
a real pytest run or a static check on the candidate's AST.

The gate order is deliberate -- cheap static checks run before expensive
executions, and the two behavioural gates (passes clean / fails mutant) are the
ones that carry the actual claim.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum

from ..mutation.models import Mutant, MutantStatus
from .runner import SubjectRunner


class Rejection(str, Enum):
    """Structured rejection codes, fed back to the agent and into evidence."""

    NO_CODE = "NO_CODE"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    NO_TEST_FUNCTION = "NO_TEST_FUNCTION"
    FORBIDDEN_PATTERN = "FORBIDDEN_PATTERN"
    NO_ASSERTION = "NO_ASSERTION"
    COLLECTION_FAILED = "COLLECTION_FAILED"
    CLEAN_HEAD_FAILED = "CLEAN_HEAD_FAILED"
    TARGET_MUTANT_SURVIVED = "TARGET_MUTANT_SURVIVED"
    NON_BEHAVIOURAL_FAILURE = "NON_BEHAVIOURAL_FAILURE"
    FLAKY_RESULT = "FLAKY_RESULT"
    RUNTIME_BUDGET_EXCEEDED = "RUNTIME_BUDGET_EXCEEDED"


# Patterns that would let a "test" cheat rather than assert on behavior:
# skipping itself, inspecting source, shelling out, or reaching the network.
_FORBIDDEN = [
    (re.compile(r"\bpytest\.skip\b"), "pytest.skip"),
    (re.compile(r"\bpytest\.xfail\b"), "pytest.xfail"),
    (re.compile(r"@pytest\.mark\.(skip|xfail)"), "skip/xfail marker"),
    (re.compile(r"\bimport\s+(inspect|subprocess|socket|requests|urllib)\b"), "forbidden import"),
    (re.compile(r"\bfrom\s+(inspect|subprocess|socket|requests|urllib)\b"), "forbidden import"),
    (re.compile(r"\b(inspect\.getsource|__file__|open\s*\()"), "source inspection"),
    (re.compile(r"\bmonkeypatch\b|\bunittest\.mock\b|\bMagicMock\b"), "mocking"),
    (re.compile(r"\bsys\.exit\b|\bos\.system\b|\bexec\s*\(|\beval\s*\("), "process control"),
]


@dataclass
class AdmissionReport:
    """Full record of why a candidate was accepted or rejected."""

    admitted: bool
    code: Rejection | None = None
    message: str = ""
    feedback: str = ""          # actionable text handed back to the agent
    clean_duration_s: float = 0.0
    target_status: str = ""
    gates_passed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "admitted": self.admitted,
            "code": self.code.value if self.code else None,
            "message": self.message,
            "clean_duration_s": round(self.clean_duration_s, 3),
            "target_status": self.target_status,
            "gates_passed": self.gates_passed,
        }


def _static_checks(code: str) -> tuple[Rejection, str] | None:
    """Cheap AST/regex gates that need no test execution."""
    if not code.strip():
        return (Rejection.NO_CODE, "empty candidate")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return (Rejection.SYNTAX_ERROR, f"line {exc.lineno}: {exc.msg}")

    tests = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("test_")
    ]
    if not tests:
        return (Rejection.NO_TEST_FUNCTION, "no function named test_*")

    for pattern, label in _FORBIDDEN:
        if pattern.search(code):
            return (Rejection.FORBIDDEN_PATTERN, f"uses {label}")

    has_assert = any(
        isinstance(n, ast.Assert) for t in tests for n in ast.walk(t)
    ) or "pytest.raises" in code
    if not has_assert:
        return (Rejection.NO_ASSERTION, "test contains no assertion")

    return None


def admit(
    runner: SubjectRunner,
    mutant: Mutant,
    code: str,
    candidate_path: str,
    repeats: int = 1,
    max_runtime_s: float = 60.0,
) -> AdmissionReport:
    """Run the full gate sequence for one candidate test.

    Returns a report whose ``feedback`` field is written to be pasted straight
    back into the agent prompt on retry.
    """
    report = AdmissionReport(admitted=False)

    # ---- Gates 1-4: static -------------------------------------------
    static = _static_checks(code)
    if static:
        code_, message = static
        report.code, report.message = code_, message
        report.feedback = f"Your previous attempt was rejected: {message}."
        return report
    report.gates_passed.append("static")

    # ---- Gate 5: passes on clean HEAD --------------------------------
    # tb="short" so rejection feedback carries the real assertion values.
    with runner.extra_tests({candidate_path: code}):
        clean = runner.run_suite([candidate_path], tb="short")
    report.clean_duration_s = clean.duration_s

    if clean.collection_broken:
        report.code = Rejection.COLLECTION_FAILED
        report.message = "pytest could not collect the candidate"
        report.feedback = (
            "Your previous attempt could not even be imported by pytest:\n"
            f"{_tail(clean.stdout + clean.stderr)}\n"
            "Fix the imports and make sure the file is valid Python."
        )
        return report

    if not clean.passed:
        report.code = Rejection.CLEAN_HEAD_FAILED
        report.message = "candidate fails against correct code"
        report.feedback = (
            "Your previous attempt FAILED against the CORRECT implementation, "
            "so its expected value is wrong. pytest reported:\n"
            f"{_tail(clean.stdout)}\n"
            "Re-read the source above and assert what the correct code actually "
            "returns for your chosen inputs."
        )
        return report
    report.gates_passed.append("clean_head")

    if clean.duration_s > max_runtime_s:
        report.code = Rejection.RUNTIME_BUDGET_EXCEEDED
        report.message = f"candidate took {clean.duration_s:.1f}s"
        report.feedback = "Your previous attempt was too slow. Use cheaper inputs."
        return report

    # ---- Gate 6: fails on the targeted mutant ------------------------
    run = runner.run_mutant(
        mutant, selection=[candidate_path], extra={candidate_path: code}
    )
    report.target_status = run.status.value

    if run.status is MutantStatus.SURVIVED:
        report.code = Rejection.TARGET_MUTANT_SURVIVED
        report.message = "candidate does not detect the injected fault"
        report.feedback = (
            "Your previous attempt PASSED even with the bug present, so it does "
            "not detect the fault. It passed on correct code, which is good — "
            "keep that, but choose input values where the buggy line actually "
            "changes the result, and assert on that difference."
        )
        return report

    if run.status in (MutantStatus.INVALID, MutantStatus.ERROR, MutantStatus.TIMEOUT):
        report.code = Rejection.NON_BEHAVIOURAL_FAILURE
        report.message = f"non-behavioural outcome: {run.status.value}"
        report.feedback = (
            "Your previous attempt failed for a non-behavioural reason "
            f"({run.status.value}). Assert on return values, not on crashes."
        )
        return report
    report.gates_passed.append("kills_target")

    # ---- Gate 7: repeat for flakiness --------------------------------
    for _ in range(max(0, repeats - 1)):
        with runner.extra_tests({candidate_path: code}):
            again = runner.run_suite([candidate_path])
        if not again.passed:
            report.code = Rejection.FLAKY_RESULT
            report.message = "candidate is not deterministic on clean HEAD"
            report.feedback = (
                "Your previous attempt did not give the same result on repeated "
                "runs. Avoid randomness, time, and ordering assumptions."
            )
            return report
    if repeats > 1:
        report.gates_passed.append("repeat_stable")

    report.admitted = True
    report.message = "passes clean HEAD and detects the injected fault"
    return report


def _tail(text: str, limit: int = 1400) -> str:
    """Trim pytest output down to the part a model can act on.

    Sized to preserve a ``--tb=short`` traceback, which is what tells the agent
    the concrete expected-vs-actual values it got wrong. Trimming this too
    aggressively is what made the first retry loop useless.
    """
    text = text.strip()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    keep = lines[-28:] if len(lines) > 28 else lines
    out = "\n".join(keep)
    return out[-limit:]

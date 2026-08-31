"""The test-author agent and its context conditions.

Placebo compares the *same local model* under different scaffolding, so any
measured difference is attributable to harness design rather than model choice.

Conditions
----------
A  implementation-aware   sees the function source; asked to write tests.
                          This is the realistic baseline: what a developer gets
                          today by asking a coding assistant for more tests.
B  mutant-aware           additionally sees the one-line diff of a concrete,
                          known-detectable evaluation fault it must catch.
C  contract-grounded      sees the signature and docstring but NOT the body,
                          plus the fault description. Tests written against the
                          contract rather than against current behavior.

Each condition can run with or without the verification retry loop, which feeds
structured rejection codes from the admission gates back into the prompt.
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from ..mutation.models import Mutant
from ..verification.admission import AdmissionReport, Rejection, admit
from ..verification.prober import extract_expressions, observe, synthesise_test
from ..verification.runner import SubjectRunner
from .llm import Completion, LocalModel

SYSTEM = (
    "You are a meticulous Python test engineer. You write focused, deterministic "
    "pytest tests that assert on real behavior. You output only code."
)

_RULES = """\
Requirements:
- Output one complete Python file and nothing else.
- Begin with `import semver`.
- Define exactly one function named `{fn_name}`.
- Use plain `assert` statements (or `pytest.raises`) on real return values.
- Do not use mocks, monkeypatch, skips, xfail, subprocess, network, or source
  inspection.
- Choose concrete, deterministic input values.

Output only the Python file inside one ```python code block."""

PROMPT_A = """\
Here is a function from the Python library `semver`:

```python
{source}
```

Write a pytest test for this function that would catch a subtle regression in
its logic. Focus on boundary values and edge cases rather than the obvious
happy path.

""" + _RULES

# Historical benchmark wording below says the regression slips past the
# "existing test suite". In the controlled authoring benchmark that means the
# hypothetical generated suite being improved, not semver's expert suite (the
# discovery faults are deliberately known-detectable). It is retained verbatim
# so the checked-in code matches the submitted raw trajectories.
PROMPT_B = """\
Here is the CURRENT, CORRECT source of a function from the Python library
`semver`:

```python
{source}
```

A specific regression is known to slip past the existing test suite. It changes
exactly this line:

```diff
{diff}
```

Write ONE pytest test that PASSES against the correct code above and FAILS when
that change is present. Pick input values where the two versions produce
different results.

""" + _RULES

PROMPT_C = """\
Here is the CONTRACT of a function from the Python library `semver`. You are
deliberately NOT shown its body, so you must reason about what it is specified
to do rather than about how it currently does it.

```python
{contract}
```

A regression is known to slip past the existing test suite. It affects this
line of the implementation:

```diff
{diff}
```

Write ONE pytest test that asserts the CONTRACTED behavior. It must pass
against a correct implementation and fail when the regression above is present.

""" + _RULES

RETRY_SUFFIX = """\

---
{feedback}

Write a corrected version of the whole file now."""


PROMPT_D = """\
Here is the CURRENT, CORRECT source of a function from the Python library
`semver`:

```python
{source}
```

A regression is known to slip past the existing test suite. It changes exactly
this line:

```diff
{diff}
```

Your job is ONLY to choose inputs. Do NOT write assertions and do NOT predict
any return value — those will be measured by running the real code.

List up to 6 single-line Python EXPRESSIONS that call into `semver` and whose
result you expect to DIFFER between the correct code and the regression above.
Prefer values near the boundary the changed line controls.

Rules:
- one expression per line, no assignments, no `assert`, no comments
- each line must be a valid Python expression starting with `semver.`
- wrap the list in one ```python code block

Example of the required shape (not the answer):
```python
semver.Version.parse("1.2.3").bump_minor()
semver.Version.parse("0.0.1") < semver.Version.parse("0.0.2")
```
"""


@dataclass
class AuthorConfig:
    """One experimental condition."""

    name: str
    condition: str = "B"           # "A" | "B" | "C" | "D"
    max_attempts: int = 3          # 1 disables the verification retry loop
    repeats: int = 1               # flakiness re-runs inside admission

    @property
    def uses_verification_loop(self) -> bool:
        return self.max_attempts > 1

    @property
    def is_oracle_grounded(self) -> bool:
        return self.condition == "D"


@dataclass
class Attempt:
    """One generate-then-verify cycle."""

    index: int
    code: str
    report: AdmissionReport
    completion: Completion

    def to_dict(self) -> dict:
        return {
            "attempt": self.index,
            "code": self.code,
            "admission": self.report.to_dict(),
            "output_tokens": self.completion.output_tokens,
            "duration_s": round(self.completion.duration_s, 2),
        }


@dataclass
class AuthoringResult:
    """Outcome of authoring a test for one mutant under one condition."""

    mutant_id: str
    condition: str
    admitted_code: str | None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def admitted(self) -> bool:
        return self.admitted_code is not None

    @property
    def attempts_used(self) -> int:
        return len(self.attempts)

    def to_dict(self) -> dict:
        return {
            "mutant_id": self.mutant_id,
            "condition": self.condition,
            "admitted": self.admitted,
            "attempts_used": self.attempts_used,
            "admitted_code": self.admitted_code,
            "attempts": [a.to_dict() for a in self.attempts],
        }


# --------------------------------------------------------------------------
# Source extraction
# --------------------------------------------------------------------------


def function_source(path: Path, qualname: str) -> str:
    """Full source text of `qualname` (supports one level of nesting)."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    def walk(nodes, remaining):
        for node in nodes:
            if getattr(node, "name", None) != remaining[0]:
                continue
            if len(remaining) == 1:
                return ast.get_source_segment(source, node)
            found = walk(getattr(node, "body", []), remaining[1:])
            if found:
                return found
        return None

    return walk(tree.body, qualname.split(".")) or ""


def function_contract(path: Path, qualname: str) -> str:
    """Signature + docstring only, with the body elided.

    This is what condition C sees. Withholding the body is the point: a test
    written against current behavior cannot detect that the behavior is wrong.
    """
    src = function_source(path, qualname)
    if not src:
        return ""
    try:
        node = ast.parse(textwrap.dedent(src)).body[0]
    except (SyntaxError, IndexError):
        return ""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ""

    doc = ast.get_docstring(node, clean=False)
    header = textwrap.dedent(src).split("\n")
    # Keep every line up to the end of the signature.
    sig_end = 0
    depth = 0
    for i, line in enumerate(header):
        depth += line.count("(") - line.count(")")
        if depth == 0 and line.rstrip().endswith(":"):
            sig_end = i
            break
    signature = "\n".join(header[: sig_end + 1])
    if doc:
        return f'{signature}\n    """{doc}"""\n    ...\n'
    return f"{signature}\n    ...\n"


def extract_code(text: str) -> str:
    """Pull the first Python code block out of a model response."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        return blocks[0].strip() + "\n"
    if "def test_" in text:
        return textwrap.dedent(text).strip() + "\n"
    return ""


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------


class TestAuthor:
    """Generates a candidate test, then lets the oracle decide."""

    def __init__(
        self,
        model: LocalModel,
        runner: SubjectRunner,
        source_file: Path,
        candidate_path: str = "tests/test_placebo_candidate.py",
        fn_name: str = "test_placebo_candidate",
    ) -> None:
        self.model = model
        self.runner = runner
        self.source_file = Path(source_file)
        self.candidate_path = candidate_path
        self.fn_name = fn_name
        self._full_source = self.source_file.read_text(encoding="utf-8")

    def build_prompt(self, mutant: Mutant, config: AuthorConfig) -> str:
        diff = mutant.diff_line(self._full_source)
        if config.condition == "A":
            return PROMPT_A.format(
                source=function_source(self.source_file, mutant.qualname)[:4000],
                fn_name=self.fn_name,
            )
        if config.condition == "C":
            contract = function_contract(self.source_file, mutant.qualname)
            if not contract:  # no usable contract -> fall back to B
                contract = function_source(self.source_file, mutant.qualname)[:4000]
            return PROMPT_C.format(contract=contract[:4000], diff=diff, fn_name=self.fn_name)
        return PROMPT_B.format(
            source=function_source(self.source_file, mutant.qualname)[:4000],
            diff=diff,
            fn_name=self.fn_name,
        )

    def author_oracle_grounded(
        self, mutant: Mutant, config: AuthorConfig
    ) -> AuthoringResult:
        """Condition D: the model chooses inputs, the oracle supplies values.

        The measured dominant failure of every prompt-only condition is the
        model asserting a wrong expected value. Here it never states one. It
        proposes candidate expressions; those are executed against clean HEAD
        and against the mutant; and the assertion is synthesized from what
        clean HEAD actually returned, restricted to expressions that genuinely
        differ under the fault.
        """
        result = AuthoringResult(
            mutant_id=mutant.id, condition=config.name, admitted_code=None
        )
        prompt = PROMPT_D.format(
            source=function_source(self.source_file, mutant.qualname)[:4000],
            diff=mutant.diff_line(self._full_source),
        )
        feedback = ""

        for i in range(1, config.max_attempts + 1):
            full = prompt + (RETRY_SUFFIX.format(feedback=feedback) if feedback else "")
            completion = self.model.complete(full, system=SYSTEM)
            expressions = extract_expressions(completion.text)

            if not expressions:
                report = AdmissionReport(
                    admitted=False, code=Rejection.NO_CODE,
                    message="no usable expressions proposed",
                )
                feedback = ("Your previous reply contained no valid single-line "
                            "expressions starting with `semver.`.")
                result.attempts.append(Attempt(i, completion.text, report, completion))
                continue

            observations = observe(self.runner, mutant, expressions)
            code, useful = synthesise_test(mutant, observations, self.fn_name)

            if not code:
                report = AdmissionReport(
                    admitted=False, code=Rejection.TARGET_MUTANT_SURVIVED,
                    message="no proposed expression distinguished clean from buggy",
                )
                observed = "\n".join(
                    f"  {o.expr} -> {o.clean_repr}" for o in observations[:6]
                )
                feedback = (
                    "None of your expressions behaved differently under the bug. "
                    f"Running them against the correct code gave:\n{observed}\n"
                    "Choose inputs closer to the boundary that the changed line "
                    "controls."
                )
                result.attempts.append(Attempt(i, "", report, completion))
                continue

            # Belt and braces: the synthesized test still faces every gate.
            report = admit(
                self.runner, mutant, code, self.candidate_path, repeats=config.repeats
            )
            result.attempts.append(Attempt(i, code, report, completion))
            if report.admitted:
                result.admitted_code = code
                return result
            feedback = report.feedback

        return result

    def author(self, mutant: Mutant, config: AuthorConfig) -> AuthoringResult:
        """Generate and verify, retrying with structured feedback."""
        if config.is_oracle_grounded:
            return self.author_oracle_grounded(mutant, config)

        result = AuthoringResult(
            mutant_id=mutant.id, condition=config.name, admitted_code=None
        )
        base_prompt = self.build_prompt(mutant, config)
        feedback = ""

        for i in range(1, config.max_attempts + 1):
            prompt = base_prompt + (RETRY_SUFFIX.format(feedback=feedback) if feedback else "")
            completion = self.model.complete(prompt, system=SYSTEM)
            code = extract_code(completion.text)

            report = admit(
                self.runner,
                mutant,
                code,
                self.candidate_path,
                repeats=config.repeats,
            )
            result.attempts.append(Attempt(i, code, report, completion))

            if report.admitted:
                result.admitted_code = code
                return result
            feedback = report.feedback

        return result

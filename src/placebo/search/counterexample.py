"""Deterministic counterexample search.

Why this exists, from measurement rather than intuition
-------------------------------------------------------
Oracle grounding removed the model's *value prediction* failures entirely. What
remained was a different failure: the model proposed inputs that simply did not
distinguish correct code from the injected fault. Of the six confirmed gaps in
semver's own suite, the three Placebo failed to close all failed this way — and
a human writing three tests by hand closed all three. The inputs existed; the
model could not find them.

Searching an input space is not a language task. It is enumeration, and a
deterministic search does it better, faster and reproducibly.

Division of labor
-----------------
    agent      : which input domain is relevant to this function?
    search     : which concrete input separates clean from faulty?
    execution  : what did each version actually return?
    verifier    : does the synthesized test still hold independently?

The search is fully deterministic: a fixed, ordered candidate pool, no sampling,
no seed. Running it twice produces the same witness. It makes **no model calls**,
so it costs nothing and cannot be blamed for a lucky generation.

Shrinking
---------
Candidates are ordered by a cost function (expression length, then literal
simplicity) and the first distinguishing candidate wins, so the reported witness
is the simplest one in the pool that does the job — the same idea as
property-based shrinking, applied to a bounded enumeration instead of a random
generator.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from ..mutation.models import Mutant
from ..verification.prober import Observation, observe
from ..verification.runner import SubjectRunner

# --------------------------------------------------------------------------
# The input domain. Boundary-heavy by construction: zeros, adjacent values,
# empty and non-empty prerelease/build parts, and the comparison boundary
# (equal operands) that off-by-one operator mutants live on.
# --------------------------------------------------------------------------

_CORE = ["0.0.0", "0.0.1", "0.1.0", "1.0.0", "1.2.3", "2.0.0"]

_PRERELEASE = ["", "-alpha", "-alpha.1", "-rc.1", "-0"]

_BUILD = ["", "+build.1", "+build.2", "+0"]

_MATCH_OPS = [">=", "<=", "==", "!=", ">", "<"]

_INVALID = ['3.14', 'b"1.2.3"', '"not-a-version"', '"1.2"', '"1"']


def _versions(limit: int = 24) -> list[str]:
    """Ordered version strings, simplest first."""
    out: list[str] = []
    for core, pre, build in product(_CORE, _PRERELEASE, _BUILD):
        out.append(f"{core}{pre}{build}")
        if len(out) >= limit:
            return out
    return out


def _unary_templates(versions: list[str]) -> list[str]:
    tpl: list[str] = []
    for v in versions:
        tpl.append(f'str(semver.Version.parse("{v}"))')
        for method in ("bump_major", "bump_minor", "bump_patch",
                       "bump_build", "bump_prerelease", "finalize_version"):
            tpl.append(f'str(semver.Version.parse("{v}").{method}())')
        tpl.append(f'semver.Version.parse("{v}").to_dict()')
        tpl.append(f'semver.Version.parse("{v}")[:4]')
        tpl.append(f'semver.Version.parse("{v}")[:5]')
    return tpl


def _binary_templates(versions: list[str]) -> list[str]:
    tpl: list[str] = []
    # Adjacent and identical pairs: where boundary operators differ.
    pairs = [(a, b) for a in versions[:10] for b in versions[:10]]
    for a, b in pairs:
        tpl.append(f'semver.Version.parse("{a}").compare("{b}")')
        tpl.append(f'semver.Version.parse("{a}").is_compatible(semver.Version.parse("{b}"))')
        for op in ("<", "<=", ">", ">=", "==", "!="):
            tpl.append(f'semver.Version.parse("{a}") {op} semver.Version.parse("{b}")')
    return tpl


def _match_templates(versions: list[str]) -> list[str]:
    tpl: list[str] = []
    for a in versions[:10]:
        for b in versions[:8]:
            for op in _MATCH_OPS:
                tpl.append(f'semver.Version.parse("{a}").match("{op}{b}")')
    return tpl


def _error_templates(_versions_unused: list[str] | None = None) -> list[str]:
    """Exception-path probes. `repr` captures the message, not just the type.

    A mutant that changes only an error *message* is invisible to
    `pytest.raises(TypeError)` but visible here.
    """
    tpl: list[str] = []
    for bad in _INVALID:
        tpl.append(f"semver.Version.parse({bad})")
    return tpl


_FUNCTION_HINTS = {
    "match": _match_templates,
    "is_compatible": _binary_templates,
    "compare": _binary_templates,
    "__lt__": _binary_templates,
    "__gt__": _binary_templates,
    "__le__": _binary_templates,
    "__ge__": _binary_templates,
    "__eq__": _binary_templates,
    "__getitem__": _unary_templates,
    "parse": _error_templates,
}


def candidate_pool(mutant: Mutant, budget: int = 900) -> list[str]:
    """Ordered candidate expressions relevant to the mutated function.

    Ordering is by ascending cost so the first hit is also the simplest one.
    """
    versions = _versions()
    method = mutant.qualname.rsplit(".", 1)[-1]

    # Relevance tier first, then cost within the tier. Sorting the whole pool
    # by length would let short, irrelevant expressions crowd out the targeted
    # ones before the budget is reached - which is exactly what hid the
    # build-metadata and error-message witnesses on the first run.
    hint = _FUNCTION_HINTS.get(method)
    tiers: list[list[str]] = []
    if hint is not None:
        tiers.append(sorted(hint(versions), key=lambda e: (len(e), e)))
    for family in (_error_templates, _binary_templates,
                   _match_templates, _unary_templates):
        if family is not hint:
            tiers.append(sorted(family(versions), key=lambda e: (len(e), e)))

    seen: set[str] = set()
    unique: list[str] = []
    for tier in tiers:
        for expr in tier:
            if expr not in seen:
                seen.add(expr)
                unique.append(expr)
    return unique[:budget]


@dataclass
class SearchResult:
    """Outcome of searching for a distinguishing input."""

    mutant_id: str
    candidates_tried: int
    witness: Observation | None
    all_distinguishing: list[Observation]

    @property
    def found(self) -> bool:
        return self.witness is not None

    def to_dict(self) -> dict:
        return {
            "mutant_id": self.mutant_id,
            "candidates_tried": self.candidates_tried,
            "found": self.found,
            "witness": self.witness.to_dict() if self.witness else None,
            "distinguishing_count": len(self.all_distinguishing),
        }


def search_counterexample(
    runner: SubjectRunner,
    mutant: Mutant,
    budget: int = 900,
    batch: int = 60,
) -> SearchResult:
    """Find the simplest input whose behavior differs under the fault.

    Candidates are evaluated in batches against clean HEAD and the mutant in one
    differential pass each, so a batch costs two subprocess launches rather than
    two per candidate.
    """
    pool = candidate_pool(mutant, budget=budget)
    distinguishing: list[Observation] = []
    tried = 0

    for start in range(0, len(pool), batch):
        chunk = pool[start : start + batch]
        tried += len(chunk)
        for obs in observe(runner, mutant, chunk):
            if obs.distinguishes:
                distinguishing.append(obs)
        if distinguishing:
            break  # pool is cost-ordered, so the earliest batch holds the simplest

    witness = None
    if distinguishing:
        witness = min(distinguishing, key=lambda o: (len(o.expr), o.expr))

    return SearchResult(
        mutant_id=mutant.id,
        candidates_tried=tried,
        witness=witness,
        all_distinguishing=distinguishing,
    )


def synthesize_from_witness(
    mutant: Mutant, result: SearchResult, fn_name: str, extra: int = 2
) -> str:
    """Build a test from the minimal witness plus a few corroborating inputs."""
    if not result.found or result.witness is None:
        return ""

    chosen = [result.witness]
    for obs in result.all_distinguishing:
        if len(chosen) >= 1 + extra:
            break
        if obs.expr != result.witness.expr:
            chosen.append(obs)

    lines = [
        "import pytest",
        "import semver",
        "",
        "",
        f"def {fn_name}():",
        f'    """Detects: {mutant.label}',
        "",
        "    Input found by deterministic counterexample search; expected values",
        "    observed by executing the reference implementation.",
        '    """',
    ]
    for obs in chosen:
        if obs.clean_ok:
            lines.append(f"    assert repr({obs.expr}) == {obs.clean_repr!r}")
        else:
            # Clean code raises on this input. Asserting only the exception
            # type would miss a fault that changes just the message - which is
            # exactly the `'...%s' % type` -> `'...%s' * type` mutant, where
            # both versions raise TypeError and only the text differs.
            exc_type, _, message = obs.clean_repr.partition(": ")
            lines.append(f"    with pytest.raises({exc_type.strip()}) as excinfo:")
            lines.append(f"        {obs.expr}")
            if message:
                lines.append(f"    assert str(excinfo.value) == {message!r}")
    return "\n".join(lines) + "\n"

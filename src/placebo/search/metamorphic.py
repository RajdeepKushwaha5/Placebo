"""Metamorphic properties: a level-3 oracle that hardcodes no expected value.

The oracle problem, restated
----------------------------
Placebo's default oracle is a *snapshot*: run the input against the reference
implementation and record whatever came back. That pins behavior against
change, not against error. If the implementation is already wrong, the snapshot
records the wrong answer as expected.

A metamorphic property sidesteps this. It asserts a *relationship between
executions* rather than a literal output:

    parse(str(v)) == v                     round trip
    compare(a, b) == -compare(b, a)        antisymmetry
    (a < b) == (b > a)                     comparison duality
    finalize(finalize(v)) == finalize(v)   idempotence
    bump_minor(v).minor == v.minor + 1     algebraic step

None of these mentions a concrete expected value, so none can be poisoned by a
pre-existing bug in the reference. They are true of any *correct* semver
implementation, which is why they sit at level 3 of the oracle hierarchy in
`docs/LIMITATIONS.md` rather than level 4.

Scope, honestly
---------------
These properties are hand-written for this subject. That is a real limit: they
encode a human's understanding of the specification, so they inherit that
human's mistakes. What they do *not* inherit is the implementation's mistakes,
and that is the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..mutation.models import Mutant
from ..verification.prober import observe
from ..verification.runner import SubjectRunner

# Each property is a boolean expression that must evaluate True on any correct
# implementation, for every version string substituted into {a} and {b}.
PROPERTIES: list[tuple[str, str, str]] = [
    (
        "round_trip",
        "parsing the string form of a version returns the same version",
        'semver.Version.parse(str(semver.Version.parse("{a}"))) '
        '== semver.Version.parse("{a}")',
    ),
    (
        "compare_antisymmetry",
        "compare(a, b) is the negation of compare(b, a)",
        'semver.Version.parse("{a}").compare("{b}") '
        '== -semver.Version.parse("{b}").compare("{a}")',
    ),
    (
        "compare_self_is_zero",
        "a version compares equal to itself",
        'semver.Version.parse("{a}").compare("{a}") == 0',
    ),
    (
        "lt_gt_duality",
        "a < b holds exactly when b > a",
        '(semver.Version.parse("{a}") < semver.Version.parse("{b}")) '
        '== (semver.Version.parse("{b}") > semver.Version.parse("{a}"))',
    ),
    (
        "le_is_lt_or_eq",
        "a <= b holds exactly when a < b or a == b",
        '(semver.Version.parse("{a}") <= semver.Version.parse("{b}")) '
        '== (semver.Version.parse("{a}") < semver.Version.parse("{b}") '
        'or semver.Version.parse("{a}") == semver.Version.parse("{b}"))',
    ),
    (
        "finalize_idempotent",
        "finalizing an already-final version changes nothing",
        'semver.Version.parse("{a}").finalize_version().finalize_version() '
        '== semver.Version.parse("{a}").finalize_version()',
    ),
    (
        "finalize_clears_prerelease",
        "a finalized version has no prerelease part",
        'semver.Version.parse("{a}").finalize_version().prerelease is None',
    ),
    (
        "bump_minor_steps_by_one",
        "bumping the minor part increases it by exactly one and zeroes patch",
        '(semver.Version.parse("{a}").bump_minor().minor '
        '== semver.Version.parse("{a}").minor + 1) '
        'and (semver.Version.parse("{a}").bump_minor().patch == 0)',
    ),
    (
        "bump_major_steps_by_one",
        "bumping the major part increases it by exactly one and zeroes the rest",
        '(semver.Version.parse("{a}").bump_major().major '
        '== semver.Version.parse("{a}").major + 1) '
        'and (semver.Version.parse("{a}").bump_major().minor == 0)',
    ),
    (
        "bump_produces_greater",
        "a bumped version is strictly greater than the original",
        'semver.Version.parse("{a}").bump_patch() > semver.Version.parse("{a}")',
    ),
    (
        "match_eq_agrees_with_equality",
        'match("==x") agrees with ==',
        'semver.Version.parse("{a}").match("==" + "{b}") '
        '== (semver.Version.parse("{a}") == semver.Version.parse("{b}"))',
    ),
    (
        "match_ge_is_gt_or_eq",
        'match(">=x") holds exactly when > or ==',
        'semver.Version.parse("{a}").match(">=" + "{b}") '
        '== (semver.Version.parse("{a}") >= semver.Version.parse("{b}"))',
    ),
]

# Deliberately boundary-heavy: equal operands, adjacent values, and
# prerelease/build variants, since that is where ordering faults live.
PAIRS: list[tuple[str, str]] = [
    ("1.2.3", "1.2.3"),
    ("0.0.0", "0.0.0"),
    ("1.2.3", "1.2.4"),
    ("1.2.3", "1.3.0"),
    ("1.2.3", "2.0.0"),
    ("0.0.1", "0.1.0"),
    ("1.0.0-alpha", "1.0.0"),
    ("1.0.0-alpha.1", "1.0.0-alpha.2"),
    ("1.0.0+build.1", "1.0.0+build.2"),
    ("1.0.0-rc.1+build.9", "1.0.0"),
]


@dataclass
class PropertyResult:
    """Whether one metamorphic property survived a fault."""

    name: str
    description: str
    holds_on_clean: bool
    violated_by_fault: bool
    example: str = ""

    @property
    def detects(self) -> bool:
        """The property is a valid detector only if it holds on clean code."""
        return self.holds_on_clean and self.violated_by_fault

    def to_dict(self) -> dict:
        return {
            "property": self.name,
            "description": self.description,
            "holds_on_clean": self.holds_on_clean,
            "violated_by_fault": self.violated_by_fault,
            "detects": self.detects,
            "example": self.example,
        }


def instantiate(limit_pairs: int = 10) -> list[tuple[str, str]]:
    """All (property_name, expression) instances to evaluate."""
    out: list[tuple[str, str]] = []
    for name, _desc, template in PROPERTIES:
        for a, b in PAIRS[:limit_pairs]:
            out.append((name, template.format(a=a, b=b)))
    return out


def check_properties(
    runner: SubjectRunner, mutant: Mutant, limit_pairs: int = 10
) -> list[PropertyResult]:
    """Evaluate every property on clean code and under the injected fault.

    A property *detects* the fault when it is True everywhere on clean code and
    False somewhere under the fault. No expected output is ever hardcoded.
    """
    instances = instantiate(limit_pairs)
    observations = observe(runner, mutant, [expr for _n, expr in instances])
    by_expr = {o.expr: o for o in observations}

    grouped: dict[str, list] = {}
    for name, expr in instances:
        grouped.setdefault(name, []).append(by_expr.get(expr))

    results: list[PropertyResult] = []
    for name, desc, _template in PROPERTIES:
        seen = [o for o in grouped.get(name, []) if o is not None]
        if not seen:
            continue
        holds_clean = all(o.clean_ok and o.clean_repr == "True" for o in seen)
        violated = any(o.mutant_repr != "True" for o in seen)
        example = ""
        for o in seen:
            if o.clean_repr == "True" and o.mutant_repr != "True":
                example = o.expr
                break
        results.append(
            PropertyResult(name, desc, holds_clean, violated, example)
        )
    return results


def synthesize_property_test(
    mutant: Mutant, results: list[PropertyResult], fn_name: str
) -> str:
    """Build a test asserting the properties that detect this fault.

    The assertions contain no recorded output value, so unlike a snapshot
    witness this test cannot encode a pre-existing bug as expected behavior.
    """
    detectors = [r for r in results if r.detects and r.example]
    if not detectors:
        return ""

    lines = [
        "import semver",
        "",
        "",
        f"def {fn_name}():",
        f'    """Detects: {mutant.label}',
        "",
        "    Asserts metamorphic properties - relationships that hold for any",
        "    correct implementation. No expected value is hardcoded, so this",
        "    test does not inherit the reference implementation's behavior.",
        '    """',
    ]
    for result in detectors:
        lines.append(f"    # {result.description}")
        lines.append(f"    assert {result.example}")
    return "\n".join(lines) + "\n"

"""Discovery / held-out mutant split.

The split is the integrity mechanism of the whole evaluation. Without it,
Placebo would be graded on exactly the faults it was shown, which measures
nothing but its ability to copy a diff into an assertion.

Design decisions, and why:

* **Same functions, different locations.** Held-out mutants live in the same
  functions the agent worked on, but at different source spans. A pure
  cross-function holdout would be unanswerable (a test for `bump_minor` cannot
  be expected to catch a fault in `parse`) and would produce a null result for
  every condition. Same-function/different-location is a real generalisation
  question with a plausible signal.

* **Same-line siblings are excluded.** A sibling mutant on the identical source
  span (e.g. `<`->`<=` when discovery used `<`->`>`) leaks the answer: any test
  pinning that boundary kills both trivially.

* **Frozen before generation.** The manifest is written, hashed, and never
  recomputed. The agent is never given held-out ids, and held-out results are
  reported only in aggregate, after generation is complete.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .models import Mutant


@dataclass
class Split:
    """A frozen discovery/held-out partition."""

    discovery: list[Mutant]
    held_out: list[Mutant]
    seed: int

    @property
    def fingerprint(self) -> str:
        """Hash over both id sets, so tampering is detectable."""
        payload = json.dumps(
            {
                "discovery": sorted(m.id for m in self.discovery),
                "held_out": sorted(m.id for m in self.held_out),
                "seed": self.seed,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_manifest(self) -> dict:
        return {
            "seed": self.seed,
            "fingerprint": self.fingerprint,
            "discovery_count": len(self.discovery),
            "held_out_count": len(self.held_out),
            "discovery": [m.to_dict() for m in self.discovery],
            "held_out": [m.to_dict() for m in self.held_out],
        }

    def assert_disjoint(self) -> None:
        """Fail loudly if the two sets ever overlap."""
        overlap = {m.id for m in self.discovery} & {m.id for m in self.held_out}
        if overlap:
            raise AssertionError(f"split leakage: {sorted(overlap)}")
        spans = {(m.file, m.span_start, m.span_end) for m in self.discovery}
        leaked = [
            m.id for m in self.held_out
            if (m.file, m.span_start, m.span_end) in spans
        ]
        if leaked:
            raise AssertionError(f"same-span sibling leakage: {sorted(leaked)}")


def build_split(
    discovery: list[Mutant],
    candidates: list[Mutant],
    killable: set[str],
    per_function: int = 3,
    seed: int = 1729,
) -> Split:
    """Choose held-out mutants for the functions covered by `discovery`.

    `killable` restricts held-out mutants to ones the expert human suite already
    kills, so every held-out mutant is known to be detectable in principle. That
    keeps equivalent and undetectable mutants out of the denominator.
    """
    discovery_ids = {m.id for m in discovery}
    discovery_spans = {(m.file, m.span_start, m.span_end) for m in discovery}
    target_functions = {m.qualname for m in discovery}

    by_function: dict[str, list[Mutant]] = {}
    for m in candidates:
        if m.qualname not in target_functions:
            continue
        if m.id in discovery_ids:
            continue
        if (m.file, m.span_start, m.span_end) in discovery_spans:
            continue  # same-line sibling: leaks the boundary
        if m.id not in killable:
            continue  # not known to be detectable; would poison the metric
        by_function.setdefault(m.qualname, []).append(m)

    held_out: list[Mutant] = []
    for fn in sorted(by_function):
        # Deterministic, seed-salted ordering; no RNG state to reproduce.
        ranked = sorted(
            by_function[fn],
            key=lambda m: hashlib.sha256(f"{seed}:{m.id}".encode()).hexdigest(),
        )
        held_out.extend(ranked[:per_function])

    split = Split(discovery=list(discovery), held_out=held_out, seed=seed)
    split.assert_disjoint()
    return split


def load_split(path: Path, all_mutants: dict[str, Mutant]) -> Split:
    """Rehydrate a frozen split, verifying the fingerprint still matches."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    split = Split(
        discovery=[all_mutants[m["id"]] for m in data["discovery"]],
        held_out=[all_mutants[m["id"]] for m in data["held_out"]],
        seed=data["seed"],
    )
    if split.fingerprint != data["fingerprint"]:
        raise ValueError(
            f"split fingerprint mismatch: manifest {data['fingerprint']}, "
            f"recomputed {split.fingerprint}"
        )
    return split

"""Evidence-carrying test patch: what the tech lead actually receives.

Placebo's output is not a chat answer and not a bare diff. It is a bundle that
carries its own evidence, so a reviewer can answer "why should I merge this?"
without re-deriving anything and without trusting the agent:

    bundle/
      manifest.json      what was produced, from what, under which environment
      patch/             the test file to merge
      evidence/          per-test proof, admission verdicts, held-out result
      VERIFY.md          how to re-check every claim yourself

The bundle is verifiable offline: ``placebo verify`` re-runs each test against
clean HEAD and against the fault it claims to detect, and reports any test whose
claim no longer holds.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..mutation.models import Mutant, write_json


@dataclass
class TestEvidence:
    """The proof attached to one admitted test."""

    test_name: str
    mutant_id: str
    fault_label: str
    fault_diff: str
    gates_passed: list[str]
    file: str
    lineno: int
    qualname: str

    def to_dict(self) -> dict:
        return {
            "test_name": self.test_name,
            "detects_fault": {
                "mutant_id": self.mutant_id,
                "label": self.fault_label,
                "diff": self.fault_diff,
                "file": self.file,
                "line": self.lineno,
                "function": self.qualname,
            },
            "proven_by": self.gates_passed,
            "claim": (
                "This test passes against the unmodified implementation and "
                "fails when the fault above is injected. Both directions were "
                "verified by executing pytest."
            ),
        }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def environment_record(model_name: str, model_digest: str) -> dict:
    """Everything needed to explain how these results were produced."""
    import importlib.metadata as md

    def version(pkg: str) -> str:
        try:
            return md.version(pkg)
        except Exception:  # noqa: BLE001 - reporting only
            return "unknown"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {
            "pytest": version("pytest"),
            "pytest-cov": version("pytest-cov"),
            "coverage": version("coverage"),
        },
        "model": {
            "name": model_name,
            "digest": model_digest,
            "temperature": 0.0,
            "seed": 7,
            "hosted": "local (Ollama)",
            "usd_cost": 0.0,
        },
    }


VERIFY_MD = """\
# Verifying this bundle

Every claim in `evidence/` is an executable statement. Nothing here asks you to
trust the agent that produced it.

## What is claimed

For each test in `patch/`, Placebo claims exactly two things:

1. it **passes** against the unmodified subject at commit `{commit}`;
2. it **fails** when one specific, named fault is injected.

Both were verified by running pytest before the test was admitted. The fault
each test detects is recorded in `evidence/tests.json`, including the exact
one-line source diff.

## Re-check it yourself

```bash
python scripts/verify_bundle.py --bundle {bundle_name}
```

This re-applies each recorded fault and re-runs the corresponding test. It
reports `HOLDS` or `BROKEN` per test and exits non-zero if any claim fails.

## What is NOT claimed

The word "proof" is deliberately avoided. These are **executable witnesses**,
not correctness proofs.

- **Not** that the asserted behavior is *correct*. This is the most important
  limitation. Expected values are a **snapshot of what the reference
  implementation currently returns**, obtained by executing it. If the
  implementation is already wrong, a witness will faithfully encode that wrong
  behavior as expected — the same implementation-copying failure this project
  criticizes, displaced one level. A witness pins behavior against *change*, not
  against *error*. Only Level 1 (an explicit specification) or Level 2
  (agreement between independent implementations) would establish correctness,
  and neither is used here.
- **Not** that the subject is bug-free. Placebo detects injected faults, not
  unknown real ones.
- **Not** that these tests are sufficient. They close specific measured gaps.
- **Not** that mutation score equals real-fault detection. It is a proxy; see
  `docs/LIMITATIONS.md`.
- **Not** that this should be merged automatically. It is a proposal for a
  qualified human reviewer.

## What IS claimed, precisely

For each test, two executable facts, both independently replayable:

1. it passes against the reference implementation at the pinned commit;
2. it fails when one specific, named single-token fault is injected.

Fact 2 is what makes it a witness rather than a snapshot: the test is
**demonstrably sensitive** to at least one concrete change. That is a weaker
claim than correctness and a much stronger one than "it passes".

## Evaluation result

The suite's aggregate evaluation is in `evidence/heldout.json`. For benchmark
bundles this is the held-out score described by the repository's split
manifests; for real-gap bundles it is closure on manually confirmed repository
gaps. The per-test claims above remain independently replayable evidence in
either case.
"""


def build_bundle(
    out_dir: Path,
    suite_code: str,
    evidences: list[TestEvidence],
    heldout_score: dict,
    environment: dict,
    subject_commit: str,
) -> Path:
    """Write a complete, self-verifying evidence bundle."""
    out_dir = Path(out_dir)
    (out_dir / "patch").mkdir(parents=True, exist_ok=True)
    (out_dir / "evidence").mkdir(parents=True, exist_ok=True)

    patch_path = out_dir / "patch" / "test_placebo_suite.py"
    patch_path.write_text(suite_code, encoding="utf-8")

    write_json(out_dir / "evidence" / "tests.json",
               [e.to_dict() for e in evidences])
    write_json(out_dir / "evidence" / "heldout.json", heldout_score)
    write_json(out_dir / "evidence" / "environment.json", environment)

    manifest = {
        "produced_by": "Placebo 0.1.0",
        "subject_commit": subject_commit,
        "tests": len(evidences),
        "patch_sha256": _sha256(suite_code),
        "patch_path": "patch/test_placebo_suite.py",
        "scope": {
            "modifies_production_code": False,
            "modifies_existing_tests": False,
            "adds_files": ["patch/test_placebo_suite.py"],
        },
        "human_approval_required": True,
        "held_out_mutation_score": heldout_score.get("mutation_score"),
        "environment": environment,
    }
    write_json(out_dir / "manifest.json", manifest)

    (out_dir / "VERIFY.md").write_text(
        VERIFY_MD.format(commit=subject_commit[:12], bundle_name=out_dir.name),
        encoding="utf-8",
    )
    return out_dir


def evidence_for(
    mutant: Mutant, test_name: str, full_source: str, gates: list[str]
) -> TestEvidence:
    return TestEvidence(
        test_name=test_name,
        mutant_id=mutant.id,
        fault_label=mutant.label,
        fault_diff=mutant.diff_line(full_source),
        gates_passed=gates,
        file=mutant.file,
        lineno=mutant.lineno,
        qualname=mutant.qualname,
    )

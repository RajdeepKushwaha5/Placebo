"""Structural validation of an evidence bundle, before anything is replayed.

Why this exists
---------------
The project's central claim is that its output carries executable evidence
rather than assertions. A bundle is that evidence. It was possible to edit the
patch inside a bundle and have `verify` replay it without complaint, because
the manifest recorded a `patch_sha256` that nothing ever compared against. A
tampered bundle would then have replayed happily and reported that every claim
held, which is the worst available failure: the verification step endorsing
something it never checked.

Validation runs before replay and is deliberately strict. A bundle that cannot
be shown to be internally consistent is not evidence, and reporting "3 of 3
claims hold" about it would be worse than reporting nothing.

Severity
--------
`ERROR` means the bundle cannot be trusted and replay should not proceed.
`WARNING` means something is missing that weakens the evidence without
invalidating it, such as an absent environment record. The distinction matters
because a bundle produced by an older version should be readable, while a
bundle whose patch does not match its own hash should not.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

REQUIRED_MANIFEST_KEYS = (
    "subject_commit", "tests", "patch_sha256", "patch_path", "scope",
)
REQUIRED_EVIDENCE_KEYS = ("test_name", "detects_fault", "proven_by")
REQUIRED_FAULT_KEYS = ("mutant_id", "label", "file", "line")


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    detail: str

    def to_dict(self) -> dict:
        return {"severity": self.severity.value, "code": self.code,
                "detail": self.detail}


@dataclass
class ValidationReport:
    bundle: str
    findings: list[Finding] = field(default_factory=list)
    manifest: dict | None = None

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def replayable(self) -> bool:
        """Whether it is honest to replay this bundle and report the result."""
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "bundle": self.bundle,
            "replayable": self.replayable,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.warnings],
        }

    def error(self, code: str, detail: str) -> None:
        self.findings.append(Finding(Severity.ERROR, code, detail))

    def warn(self, code: str, detail: str) -> None:
        self.findings.append(Finding(Severity.WARNING, code, detail))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_json(path: Path, report: ValidationReport, code: str) -> object | None:
    """Read JSON, distinguishing absent from corrupt.

    A truncated write and a missing file are different problems with different
    fixes, so they are reported differently rather than both as "unreadable".
    """
    if not path.is_file():
        report.error(code, f"{path.name} is missing")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.error(code, f"{path.name} is not valid JSON: {exc.msg} "
                           f"at line {exc.lineno}")
        return None
    except OSError as exc:  # pragma: no cover - unreadable file
        report.error(code, f"{path.name} cannot be read: {exc}")
        return None


def _resolve_inside(bundle: Path, relative: str) -> Path | None:
    """Resolve a manifest path, refusing anything that escapes the bundle.

    A manifest is data, and a bundle can arrive from anywhere, so a path in it
    must never be able to reach outside the directory it came in. Without this,
    `patch_path: "../../../../etc/passwd"` would be read and hashed.
    """
    candidate = (bundle / relative).resolve()
    try:
        candidate.relative_to(bundle.resolve())
    except ValueError:
        return None
    return candidate


def validate_bundle(bundle: Path, subject_commit: str | None = None,
                    environment: dict | None = None) -> ValidationReport:
    """Check that a bundle is internally consistent and safe to replay.

    `subject_commit` is the revision the caller intends to replay against; a
    mismatch means the recorded claims were measured against different code.
    `environment` is the current interpreter and dependency record, compared
    against the one the bundle was produced under.
    """
    bundle = Path(bundle)
    report = ValidationReport(bundle=bundle.name)

    if not bundle.is_dir():
        report.error("bundle-missing", f"no such bundle directory: {bundle}")
        return report

    manifest = _load_json(bundle / "manifest.json", report, "manifest-unreadable")
    if not isinstance(manifest, dict):
        if manifest is not None:
            report.error("manifest-shape", "manifest.json is not an object")
        return report
    report.manifest = manifest

    missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]
    if missing:
        report.error("manifest-incomplete",
                     f"manifest is missing: {', '.join(missing)}")

    # -- the patch, and whether it is the one that was measured ------------
    patch_rel = manifest.get("patch_path")
    if not patch_rel:
        report.error("patch-path-missing", "manifest does not name a patch file")
    else:
        patch_path = _resolve_inside(bundle, str(patch_rel))
        if patch_path is None:
            report.error("patch-path-escapes",
                         f"patch_path leaves the bundle: {patch_rel!r}")
        elif not patch_path.is_file():
            report.error("patch-missing", f"{patch_rel} is missing")
        else:
            recorded = manifest.get("patch_sha256")
            actual = _sha256(patch_path.read_text(encoding="utf-8"))
            if not recorded:
                report.error("patch-unhashed",
                             "manifest records no patch_sha256, so the patch "
                             "cannot be shown to be the one that was measured")
            elif actual != recorded:
                report.error(
                    "patch-tampered",
                    f"patch does not match its recorded hash "
                    f"(manifest {recorded[:12]}, actual {actual[:12]})")

    # -- the evidence itself ------------------------------------------------
    evidence = _load_json(bundle / "evidence" / "tests.json", report,
                          "evidence-unreadable")
    if evidence is None:
        pass
    elif not isinstance(evidence, list):
        report.error("evidence-shape", "evidence/tests.json is not a list")
    else:
        declared = manifest.get("tests")
        if isinstance(declared, int) and declared != len(evidence):
            report.error(
                "evidence-count",
                f"manifest declares {declared} tests, evidence holds "
                f"{len(evidence)}")
        for index, entry in enumerate(evidence):
            if not isinstance(entry, dict):
                report.error("evidence-entry-shape",
                             f"evidence entry {index} is not an object")
                continue
            absent = [k for k in REQUIRED_EVIDENCE_KEYS if k not in entry]
            if absent:
                report.error(
                    "evidence-entry-incomplete",
                    f"{entry.get('test_name', f'entry {index}')} is missing: "
                    f"{', '.join(absent)}")
            fault = entry.get("detects_fault")
            if isinstance(fault, dict):
                lacking = [k for k in REQUIRED_FAULT_KEYS if k not in fault]
                if lacking:
                    report.error(
                        "evidence-fault-incomplete",
                        f"{entry.get('test_name', index)} names a fault missing: "
                        f"{', '.join(lacking)}")
            elif "detects_fault" in entry:
                report.error("evidence-fault-shape",
                             f"{entry.get('test_name', index)} has a malformed "
                             "detects_fault")

    # -- provenance ---------------------------------------------------------
    recorded_commit = manifest.get("subject_commit")
    if subject_commit and recorded_commit and recorded_commit != subject_commit:
        report.error(
            "revision-mismatch",
            f"bundle was measured against {str(recorded_commit)[:12]}, "
            f"replaying against {subject_commit[:12]}")

    bundle_env = manifest.get("environment")
    if not bundle_env:
        report.warn("environment-absent",
                    "no environment recorded, so the result cannot be "
                    "attributed to a particular interpreter or model")
    elif environment:
        for key in ("python", "pytest"):
            was, now = bundle_env.get(key), environment.get(key)
            if was and now and was != now:
                report.warn(
                    "environment-mismatch",
                    f"{key} differs: bundle recorded {was}, current is {now}")

    scope = manifest.get("scope")
    if isinstance(scope, dict):
        if scope.get("modifies_production_code"):
            report.error("scope-violation",
                         "bundle claims to modify production code; Placebo "
                         "only ever proposes tests")
    elif "scope" in manifest:
        report.error("scope-shape", "manifest scope is not an object")

    return report


def render(report: ValidationReport) -> str:
    """Human-readable validation result."""
    width = 74
    lines = ["=" * width, f"  BUNDLE VALIDATION  {report.bundle}", "=" * width]
    if not report.findings:
        lines.append("  OK    structurally consistent")
    for finding in report.findings:
        lines.append(f"  {finding.severity.value:7s} {finding.code}: {finding.detail}")
    lines.append("=" * width)
    lines.append("  replayable" if report.replayable
                 else "  NOT REPLAYABLE: the bundle cannot be trusted")
    lines.append("=" * width)
    return "\n".join(lines)

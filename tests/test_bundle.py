"""Tests for evidence bundles: building them and refusing bad ones.

The project's argument is that its output carries executable evidence rather
than assertions, so the evidence subsystem is the last place that should be
taken on trust. It was: `verify` read `patch_sha256` out of the manifest and
never compared anything against it, so a bundle whose patch had been edited
replayed happily and reported that every claim held. A verification step
endorsing something it never checked is worse than no verification step.

Each test below names the specific way a bundle can be wrong. They are written
against a bundle built by `build_bundle`, then damaged one way at a time, so a
failure says which property stopped holding rather than that "the bundle is
bad".
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.evidence.bundle import (  # noqa: E402
    build_bundle,
    environment_record,
    evidence_for,
)
from placebo.evidence.validate import validate_bundle  # noqa: E402
from placebo.mutation.models import Mutant, OperatorFamily  # noqa: E402

COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"

SUITE = (
    "import semver\n\n\n"
    "def test_placebo_01():\n"
    '    assert semver.bump_minor("1.2.3") == "1.3.0"\n'
)


def a_mutant() -> Mutant:
    return Mutant(
        file="semver/version.py", qualname="Version.bump_minor",
        operator=OperatorFamily.CONSTANT, lineno=292, col=40,
        span_start=100, span_end=101, original="1", replacement="2",
        subject_commit=COMMIT,
    )


@pytest.fixture
def bundle(tmp_path) -> Path:
    """A complete, well-formed bundle."""
    mutant = a_mutant()
    source = "x = 1\n" * 300
    evidence = [evidence_for(mutant, "test_placebo_01", source,
                             ["static", "clean_head", "kills_target"])]
    return build_bundle(
        out_dir=tmp_path / "bundle",
        suite_code=SUITE,
        evidences=evidence,
        heldout_score={"mutation_score": 0.31, "killed": ["a"], "scorable": 29},
        environment={"python": "3.13.0", "pytest": "9.0.2"},
        subject_commit=COMMIT,
    )


def manifest_of(bundle: Path) -> dict:
    return json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))


def rewrite_manifest(bundle: Path, **changes) -> None:
    manifest = manifest_of(bundle)
    manifest.update(changes)
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


# -- building --------------------------------------------------------------


def test_a_built_bundle_is_complete_and_valid(bundle):
    for relative in ("manifest.json", "VERIFY.md",
                     "patch/test_placebo_suite.py",
                     "evidence/tests.json", "evidence/heldout.json",
                     "evidence/environment.json"):
        assert (bundle / relative).is_file(), f"{relative} was not written"
    assert validate_bundle(bundle).replayable


def test_the_manifest_hashes_the_patch_it_shipped(bundle):
    """The hash is the only thing tying the manifest to the patch beside it."""
    expected = hashlib.sha256(SUITE.encode("utf-8")).hexdigest()
    assert manifest_of(bundle)["patch_sha256"] == expected


def test_the_manifest_declares_the_evidence_count(bundle):
    assert manifest_of(bundle)["tests"] == 1


def test_a_bundle_never_claims_to_modify_production_code(bundle):
    scope = manifest_of(bundle)["scope"]
    assert scope["modifies_production_code"] is False
    assert scope["modifies_existing_tests"] is False
    assert manifest_of(bundle)["human_approval_required"] is True


def test_evidence_records_the_fault_and_how_it_was_proven(bundle):
    entry = json.loads(
        (bundle / "evidence" / "tests.json").read_text(encoding="utf-8"))[0]
    assert entry["test_name"] == "test_placebo_01"
    assert entry["detects_fault"]["mutant_id"] == a_mutant().id
    assert entry["proven_by"] == ["static", "clean_head", "kills_target"]
    assert "verified by executing pytest" in entry["claim"]


def test_evidence_for_carries_the_mutants_own_identity():
    mutant = a_mutant()
    evidence = evidence_for(mutant, "t", "x = 1\n" * 300, ["static"])
    assert evidence.mutant_id == mutant.id
    assert evidence.file == mutant.file and evidence.lineno == mutant.lineno


def test_environment_record_names_the_model_and_the_interpreter():
    record = environment_record("qwen2.5:7b", "sha256:abc")
    assert record["model"]["name"] == "qwen2.5:7b"
    assert record["model"]["digest"] == "sha256:abc"
    assert "python" in record
    json.dumps(record)


# -- refusing a bundle that cannot be trusted ------------------------------


def test_a_tampered_patch_is_rejected(bundle):
    """The defect this module was written for. Editing the patch after the
    fact must not replay as though it were the measured one."""
    patch = bundle / "patch" / "test_placebo_suite.py"
    patch.write_text(SUITE + "\n\ndef test_added_later():\n    assert True\n",
                     encoding="utf-8")

    report = validate_bundle(bundle)
    assert not report.replayable
    assert "patch-tampered" in codes(report)


def test_a_single_character_edit_is_caught(bundle):
    """The interesting tampering is small: flipping an expected value."""
    patch = bundle / "patch" / "test_placebo_suite.py"
    patch.write_text(SUITE.replace('"1.3.0"', '"1.4.0"'), encoding="utf-8")
    assert "patch-tampered" in codes(validate_bundle(bundle))


def test_a_manifest_without_a_hash_is_rejected(bundle):
    """Removing the hash must not be a way to avoid the check."""
    rewrite_manifest(bundle, patch_sha256="")
    assert "patch-unhashed" in codes(validate_bundle(bundle))


def test_a_missing_patch_is_rejected(bundle):
    (bundle / "patch" / "test_placebo_suite.py").unlink()
    assert "patch-missing" in codes(validate_bundle(bundle))


def test_a_patch_path_that_escapes_the_bundle_is_refused(bundle):
    """A manifest is data and a bundle can come from anywhere, so a path in it
    must never reach outside the directory it arrived in."""
    rewrite_manifest(bundle, patch_path="../../../../etc/passwd")
    report = validate_bundle(bundle)
    assert "patch-path-escapes" in codes(report)
    assert not report.replayable


@pytest.mark.parametrize("escape", [
    "../outside.py",
    "patch/../../outside.py",
])
def test_traversal_variants_are_all_refused(bundle, escape):
    rewrite_manifest(bundle, patch_path=escape)
    assert "patch-path-escapes" in codes(validate_bundle(bundle))


def test_missing_evidence_is_rejected(bundle):
    (bundle / "evidence" / "tests.json").unlink()
    assert "evidence-unreadable" in codes(validate_bundle(bundle))


def test_truncated_json_is_reported_as_corrupt_not_missing(bundle):
    """A half-written file and an absent one need different fixes."""
    (bundle / "evidence" / "tests.json").write_text(
        '[{"test_name": "t",', encoding="utf-8")
    report = validate_bundle(bundle)
    assert "evidence-unreadable" in codes(report)
    assert any("not valid JSON" in f.detail for f in report.findings)


def test_a_corrupt_manifest_is_reported_without_raising(bundle):
    (bundle / "manifest.json").write_text("{not json", encoding="utf-8")
    report = validate_bundle(bundle)
    assert not report.replayable
    assert "manifest-unreadable" in codes(report)


def test_an_evidence_count_that_disagrees_with_the_manifest_is_rejected(bundle):
    rewrite_manifest(bundle, tests=9)
    report = validate_bundle(bundle)
    assert "evidence-count" in codes(report)
    assert any("declares 9" in f.detail for f in report.findings)


def test_an_evidence_entry_missing_its_fault_is_rejected(bundle):
    entries = json.loads(
        (bundle / "evidence" / "tests.json").read_text(encoding="utf-8"))
    del entries[0]["detects_fault"]
    (bundle / "evidence" / "tests.json").write_text(
        json.dumps(entries), encoding="utf-8")
    assert "evidence-entry-incomplete" in codes(validate_bundle(bundle))


def test_a_fault_missing_its_identity_is_rejected(bundle):
    entries = json.loads(
        (bundle / "evidence" / "tests.json").read_text(encoding="utf-8"))
    del entries[0]["detects_fault"]["mutant_id"]
    (bundle / "evidence" / "tests.json").write_text(
        json.dumps(entries), encoding="utf-8")
    assert "evidence-fault-incomplete" in codes(validate_bundle(bundle))


def test_a_manifest_missing_required_keys_is_rejected(bundle):
    manifest = manifest_of(bundle)
    del manifest["subject_commit"]
    del manifest["scope"]
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = validate_bundle(bundle)
    assert "manifest-incomplete" in codes(report)
    assert "subject_commit" in report.errors[0].detail


def test_replaying_against_another_revision_is_refused(bundle):
    """The claims were measured against one revision of the subject. Against a
    different one they are not evidence about anything."""
    report = validate_bundle(bundle, subject_commit="b" * 40)
    assert "revision-mismatch" in codes(report)
    assert not report.replayable


def test_the_matching_revision_is_accepted(bundle):
    assert validate_bundle(bundle, subject_commit=COMMIT).replayable


def test_a_bundle_claiming_to_modify_production_code_is_refused(bundle):
    rewrite_manifest(bundle, scope={"modifies_production_code": True})
    report = validate_bundle(bundle)
    assert "scope-violation" in codes(report)
    assert not report.replayable


def test_a_missing_bundle_directory_is_reported(tmp_path):
    report = validate_bundle(tmp_path / "absent")
    assert "bundle-missing" in codes(report)
    assert not report.replayable


# -- weaker evidence is a warning, not a refusal ---------------------------


def test_an_absent_environment_warns_rather_than_refuses(bundle):
    """An older bundle should still be readable; it just proves less."""
    rewrite_manifest(bundle, environment={})
    report = validate_bundle(bundle)
    assert "environment-absent" in codes(report)
    assert report.replayable, "a missing environment weakens, not invalidates"


def test_a_different_interpreter_warns(bundle):
    report = validate_bundle(
        bundle, environment={"python": "3.11.0", "pytest": "9.0.2"})
    assert "environment-mismatch" in codes(report)
    assert report.replayable
    assert any("3.11.0" in f.detail for f in report.warnings)


def test_a_matching_environment_produces_no_warning(bundle):
    report = validate_bundle(
        bundle, environment={"python": "3.13.0", "pytest": "9.0.2"})
    assert "environment-mismatch" not in codes(report)


# -- reporting -------------------------------------------------------------


def test_the_report_is_serialisable_and_separates_errors_from_warnings(bundle):
    rewrite_manifest(bundle, environment={}, tests=5)
    report = validate_bundle(bundle)
    payload = report.to_dict()
    json.dumps(payload)
    assert payload["replayable"] is False
    assert {f["code"] for f in payload["errors"]} == {"evidence-count"}
    assert {f["code"] for f in payload["warnings"]} == {"environment-absent"}


def test_rendering_names_the_reason_a_bundle_was_refused(bundle):
    from placebo.evidence.validate import render

    (bundle / "patch" / "test_placebo_suite.py").write_text("x", encoding="utf-8")
    text = render(validate_bundle(bundle))
    assert "NOT REPLAYABLE" in text
    assert "patch-tampered" in text


def test_the_shipped_bundles_validate():
    """The two bundles this repository publishes must pass their own check."""
    for name in ("bundle", "real-gap-bundle"):
        report = validate_bundle(ROOT / "artifacts" / name)
        assert report.replayable, \
            f"{name}: {[f.to_dict() for f in report.errors]}"

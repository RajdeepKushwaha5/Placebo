"""Tests for SARIF output.

Two things matter here. The document has to be structurally valid, because a
malformed one is rejected silently by code-scanning ingest and the audit
simply never appears. And the severity mapping has to stay conservative: an
audit that marks everything an error is an audit people mute.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.audit.marginal import SuiteAudit, Verdict  # noqa: E402
from placebo.audit.marginal import TestAudit as AuditRecord  # noqa: E402
from placebo.oracle import report_suite  # noqa: E402
from placebo.sarif import build, definition_lines  # noqa: E402

SOURCE = textwrap.dedent('''\
    import pytest
    import semver


    def test_valuable():
        assert semver.bump_minor("1.2.3") == "1.3.0"


    def test_harmful():
        assert repr(semver.parse("1.0.0")) == 'wrong'


    def test_redundant():
        assert semver.bump_major("1.2.3") == "2.0.0"
    ''')


def make_audit() -> SuiteAudit:
    audit = SuiteAudit(suite_name="patch", fault_corpus=10, faults_evaluated=10)
    audit.tests = [
        AuditRecord("test_valuable", True, True, verdict=Verdict.VALUABLE,
                    note="sole detector of 1 fault"),
        AuditRecord("test_harmful", False, True, verdict=Verdict.HARMFUL,
                    note="fails against correct code"),
        AuditRecord("test_redundant", True, True,
                    verdict=Verdict.REDUNDANT_WITH_EXISTING,
                    note="only re-detects 3 faults the existing suite catches"),
    ]
    return audit


def document(**kwargs) -> dict:
    return build(make_audit(), SOURCE, "tests/patch.py", **kwargs)


# -- structure -------------------------------------------------------------


def test_document_has_the_required_sarif_shape():
    doc = document()
    assert doc["version"] == "2.1.0"
    assert doc["$schema"].endswith("sarif-2.1.0.json")
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "Placebo"
    for result in run["results"]:
        assert result["ruleId"] and result["level"] and result["message"]["text"]
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] >= 1


def test_every_result_references_a_declared_rule():
    """Ingest rejects a result whose ruleId is not in the driver's rule list."""
    run = document()["runs"][0]
    declared = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert {r["ruleId"] for r in run["results"]} <= declared


def test_document_is_json_serialisable():
    json.dumps(document())


def test_results_are_anchored_to_the_test_definition():
    lines = definition_lines(SOURCE)
    run = document()["runs"][0]
    harmful = next(r for r in run["results"] if "test_harmful" in r["message"]["text"])
    assert harmful["locations"][0]["physicalLocation"]["region"]["startLine"] == \
        lines["test_harmful"]


def test_line_lookup_survives_unparseable_source():
    assert definition_lines("def (((") == {}


# -- severity is a claim, so it stays conservative -------------------------


def test_only_an_unfit_test_is_an_error():
    run = document()["runs"][0]
    errors = [r for r in run["results"] if r["level"] == "error"]
    assert len(errors) == 1
    assert "test_harmful" in errors[0]["message"]["text"]


def test_redundancy_is_a_note_not_a_warning():
    run = document()["runs"][0]
    redundant = next(r for r in run["results"]
                     if r["ruleId"] == "placebo/redundant-with-suite")
    assert redundant["level"] == "note"


def test_valuable_tests_are_not_annotated():
    """Annotating good news trains reviewers to skim the annotations."""
    run = document()["runs"][0]
    assert not any("test_valuable" in r["message"]["text"] for r in run["results"])


# -- brittleness and oracle level ------------------------------------------


def test_brittleness_warnings_are_included_when_oracles_are_supplied():
    run = document(oracles=report_suite(SOURCE))["runs"][0]
    brittle = [r for r in run["results"] if r["ruleId"].startswith("placebo/brittle-")]
    assert brittle, "the repr assertion should produce a warning"
    assert all(r["level"] == "warning" for r in brittle)


def test_snapshot_notes_are_off_by_default():
    """Every generated test is a snapshot, so annotating them all would bury
    the findings that need action."""
    without = document(oracles=report_suite(SOURCE))["runs"][0]
    assert not any(r["ruleId"] == "placebo/snapshot-oracle" for r in without["results"])

    with_notes = document(oracles=report_suite(SOURCE),
                          include_snapshot_notes=True)["runs"][0]
    notes = [r for r in with_notes["results"]
             if r["ruleId"] == "placebo/snapshot-oracle"]
    assert notes
    assert all(r["level"] == "note" for r in notes)
    assert "does not establish" in notes[0]["message"]["text"]


def test_no_oracles_produces_no_brittleness_results():
    run = document()["runs"][0]
    assert not any(r["ruleId"].startswith("placebo/brittle-") for r in run["results"])


# -- scope is carried with the findings ------------------------------------


def test_invocation_records_how_much_of_the_corpus_was_evaluated():
    """A partial audit's findings mean less, so the scope travels with them."""
    audit = make_audit()
    audit.faults_evaluated = 4
    audit.budget_exhausted = True

    properties = build(audit, SOURCE, "tests/patch.py")["runs"][0]["invocations"][0]
    assert properties["properties"]["faultCorpus"] == 10
    assert properties["properties"]["faultsEvaluated"] == 4
    assert properties["properties"]["budgetExhausted"] is True


def test_an_empty_audit_produces_a_valid_empty_document():
    doc = build(SuiteAudit(suite_name="none"), "", "tests/none.py")
    assert doc["runs"][0]["results"] == []
    assert doc["runs"][0]["tool"]["driver"]["rules"] == []
    json.dumps(doc)

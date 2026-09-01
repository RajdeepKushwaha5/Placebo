"""SARIF output, so an audit can appear as code-scanning annotations.

SARIF is the format GitHub, Azure DevOps and most review tooling already read.
Emitting it means a Placebo audit shows up beside the changed lines in a pull
request instead of in a log a reviewer has to go find.

What is and is not a finding
----------------------------
A finding is something a reviewer should act on, so the mapping is deliberately
asymmetric:

    HARMFUL                   error    red or unstable against correct code;
                                       this should not merge as it stands
    REDUNDANT_WITH_SIBLING    note     the patch could be smaller
    REDUNDANT_WITH_EXISTING   note     adds review burden, not protection
    UNPROVEN                  note     no measured sensitivity, which is not
                                       the same as no value
    brittleness               warning  may fail without behaviour changing

`VALUABLE` is not emitted. A tool that annotates good news trains people to
skim its annotations, and the value of a marginal-value audit is that its
output is short.

Severity is a claim, so it is kept conservative. Only HARMFUL is an error,
because only HARMFUL is established by execution against correct code. UNPROVEN
in particular is a note and never a warning: it reports what was measured under
one fault corpus, not a defect.
"""

from __future__ import annotations

import ast
from typing import Iterable

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
VERSION = "2.1.0"
TOOL_URI = "https://github.com/RajdeepKushwaha5/Placebo"

# verdict -> (rule id, SARIF level, short description)
_VERDICT_RULES = {
    "HARMFUL": (
        "placebo/unfit-test", "error",
        "Test is red or unstable against correct code",
    ),
    "REDUNDANT_WITH_SIBLING": (
        "placebo/redundant-with-sibling", "note",
        "Another test in this patch detects the same faults",
    ),
    "REDUNDANT_WITH_EXISTING": (
        "placebo/redundant-with-suite", "note",
        "Only re-detects faults the existing suite already catches",
    ),
    "UNPROVEN": (
        "placebo/no-measured-sensitivity", "note",
        "No marginal fault sensitivity under the evaluated fault models",
    ),
}

_BRITTLE_RULES = {
    "exception-message": "Asserts exact exception wording",
    "representation": "Asserts a display form rather than a value",
    "nondeterministic": "Depends on a value that changes between runs",
    "serialisation": "Asserts serialiser formatting",
}

_ORACLE_RULE = "placebo/snapshot-oracle"


def definition_lines(source: str) -> dict[str, int]:
    """Line number of each test's definition, for anchoring annotations."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return {
        node.name: node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _location(path: str, line: int) -> dict:
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": path, "uriBaseId": "%SRCROOT%"},
            "region": {"startLine": max(1, line)},
        }
    }


def _rule(rule_id: str, name: str, description: str, level: str) -> dict:
    return {
        "id": rule_id,
        "name": name,
        "shortDescription": {"text": description},
        "defaultConfiguration": {"level": level},
        "help": {
            "text": (
                "Placebo measures what a test would catch that nothing else "
                "already catches. Verdicts come from executing the suite "
                "against injected faults, not from static analysis."
            )
        },
    }


def build(audit, source: str, path: str,
          oracles: Iterable | None = None,
          include_snapshot_notes: bool = False) -> dict:
    """Render one audit as a SARIF 2.1.0 document.

    `audit` is a SuiteAudit, `source` the patch text and `path` its
    repository-relative location. `oracles` are OracleReports for the same
    patch, if oracle labelling was run.
    """
    lines = definition_lines(source)
    results: list[dict] = []
    used_rules: dict[str, dict] = {}

    for record in audit.tests:
        verdict = record.verdict.value
        if verdict not in _VERDICT_RULES:
            continue  # VALUABLE is deliberately not an annotation
        rule_id, level, description = _VERDICT_RULES[verdict]
        used_rules.setdefault(
            rule_id, _rule(rule_id, verdict.lower(), description, level))
        results.append({
            "ruleId": rule_id,
            "level": level,
            "message": {"text": f"{record.name}: {record.note or description}."},
            "locations": [_location(path, lines.get(record.name, 1))],
        })

    for report in oracles or []:
        for warning in report.warnings:
            rule_id = f"placebo/brittle-{warning.kind}"
            used_rules.setdefault(rule_id, _rule(
                rule_id, f"brittle-{warning.kind}",
                _BRITTLE_RULES.get(warning.kind, "Brittle assertion"), "warning"))
            results.append({
                "ruleId": rule_id,
                "level": "warning",
                "message": {"text": f"{report.test}: {warning.detail}."},
                "locations": [_location(path, warning.line)],
            })

        if include_snapshot_notes and not report.level.claims_correctness:
            used_rules.setdefault(_ORACLE_RULE, _rule(
                _ORACLE_RULE, "snapshot-oracle",
                "Expected value records current behaviour, not verified correctness",
                "note"))
            results.append({
                "ruleId": _ORACLE_RULE,
                "level": "note",
                "message": {"text": (
                    f"{report.test}: {report.level.label}. {report.reason}. "
                    "This detects regressions; it does not establish that the "
                    "current behaviour is correct."
                )},
                "locations": [_location(path, lines.get(report.test, 1))],
            })

    return {
        "$schema": SCHEMA,
        "version": VERSION,
        "runs": [{
            "tool": {"driver": {
                "name": "Placebo",
                "informationUri": TOOL_URI,
                "rules": [used_rules[key] for key in sorted(used_rules)],
            }},
            "results": results,
            "invocations": [{
                "executionSuccessful": True,
                "properties": {
                    "faultCorpus": audit.fault_corpus,
                    "faultsEvaluated": audit.faults_evaluated,
                    "budgetExhausted": audit.budget_exhausted,
                },
            }],
        }],
    }

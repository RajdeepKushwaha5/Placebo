"""Cross-check every headline claim against the data that backs it.

Ground rule: "Connect every claim about your results to the evidence you
submit." This script enforces that mechanically, so a stale report or a number
edited by hand in the README fails loudly instead of shipping.

It re-derives each claim from the artifacts and compares. Exits non-zero on any
mismatch.

Usage:
  python scripts/check_consistency.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UPSTREAM_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"

checks: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    checks.append((ok, f"{label}{(' - ' + detail) if detail else ''}"))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def check_bundle(bundle: Path, label: str) -> None:
    manifest = load(bundle / "manifest.json")
    if not manifest:
        check(False, f"{label} bundle manifest exists")
        return
    patch = (bundle / manifest["patch_path"]).read_text(encoding="utf-8")
    digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    check(digest == manifest["patch_sha256"],
          f"{label} bundle patch sha256 matches its manifest")
    evidence = load(bundle / "evidence" / "tests.json") or []
    check(len(evidence) == manifest["tests"],
          f"{label} bundle evidence count matches the manifest",
          f"{len(evidence)} entries")
    check(manifest["scope"]["modifies_production_code"] is False,
          f"{label} bundle does not modify production code")


def main() -> int:
    census = load(ROOT / "artifacts" / "census_summary.json")
    triage = load(ROOT / "artifacts" / "survivor_triage.json")
    results = load(ROOT / "experiments" / "results.json")
    realgap = load(ROOT / "experiments" / "real_gap_closure.json")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    report_path = ROOT / "artifacts" / "report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""

    # -- 1. subject integrity ---------------------------------------------
    provenance = (ROOT / "subject" / "PROVENANCE.md").read_text(encoding="utf-8")
    check(UPSTREAM_COMMIT in provenance, "subject provenance records the pinned commit")
    subject_hashes = load(ROOT / "benchmark" / "manifests" / "subject_hashes.json")
    if subject_hashes:
        for relative, expected in subject_hashes.get("files", {}).items():
            actual = hashlib.sha256(
                (ROOT / "subject" / relative).read_bytes()
            ).hexdigest()
            check(actual == expected, f"subject hash matches: {relative}")

    # -- 2. census claims --------------------------------------------------
    if census:
        killed, scorable = census["killed"], census["scorable"]
        score = killed / scorable
        # Stored scores are rounded to 4 decimal places when written.
        check(abs(census["mutation_score"] - score) < 5e-5,
              "census mutation_score equals killed/scorable",
              f"{killed}/{scorable} = {score:.4f}")
        check(f"{score * 100:.1f}%" in readme,
              f"README quotes the census score {score * 100:.1f}%")
        check(f"({killed}/{census['total_mutants']})" in readme
              or f"{killed}/{scorable}" in readme,
              "README quotes killed/total consistent with census")

    # -- 3. triage claims --------------------------------------------------
    if triage and census:
        confirmed = triage["confirmed_real_gaps"]
        equivalent = triage["equivalent_or_contract_only"]
        check(confirmed + equivalent == triage["survivors"],
              "triage verdicts account for every survivor",
              f"{confirmed} + {equivalent} = {triage['survivors']}")
        check(triage["survivors"] == census["survived"],
              "triage survivor count matches the census")
        check(str(confirmed) in readme and "equivalent" in readme.lower(),
              f"README states {confirmed} confirmed gaps and the equivalent mutant")

    # -- 4. report matches results.json ------------------------------------
    if results and report:
        n = results["held_out_count"]
        check(f"n={n}" in report,
              f"report states the all-eligible held-out size n={n}")
        confirm_n = results.get("held_out_count_stratified", 0)
        check(f"n={confirm_n}" in report,
              f"report states the frozen confirmatory size n={confirm_n}")
        check("post-generation all-eligible" in results.get("primary_split_status", ""),
              "results label the all-eligible analysis as post-generation")
        check("frozen before generation" in results.get("stratified_split_status", ""),
              "results label the confirmatory split as pre-generation frozen")

        # Scope the search to the held-out comparison section. The report
        # contains several tables keyed by condition name, so an unscoped
        # search matches whichever happens to come first.
        section = ""
        match = re.search(r"^## Held-out comparison\s*$(.*?)(?=^## )",
                          report, re.MULTILINE | re.DOTALL)
        if match:
            section = match.group(1)
        check(bool(section), "report contains a Held-out comparison section")

        for name, meta in results["conditions"].items():
            pct = f"{meta['score']['mutation_score'] * 100:.0f}%"
            confirm_pct = f"{meta.get('score_stratified', meta['score'])['mutation_score'] * 100:.0f}%"
            row = re.search(rf"\|\s*`{re.escape(name)}`\s*\|[^\n]*", section)
            check(row is not None and pct in row.group(0),
                  f"held-out row for {name} shows all-eligible {pct}")
            check(row is not None and confirm_pct in row.group(0),
                  f"held-out row for {name} shows confirmatory {confirm_pct}")

        primary_manifest = load(ROOT / results.get("primary_manifest", ""))
        confirm_manifest = load(ROOT / results.get("stratified_manifest", ""))
        check(primary_manifest is not None and
              primary_manifest.get("fingerprint") == results["split_fingerprint"],
              "all-eligible manifest fingerprint matches results")
        check(confirm_manifest is not None and
              confirm_manifest.get("fingerprint") == results["split_fingerprint_stratified"],
              "confirmatory manifest fingerprint matches results")

    # -- 5. real-gap closure ------------------------------------------------
    if realgap:
        closed, total = realgap["gaps_closed"], realgap["confirmed_gaps"]
        check(abs(realgap["gap_closure_rate"] - closed / total) < 1e-6,
              "real-gap closure rate equals closed/confirmed",
              f"{closed}/{total}")
        check(realgap["union_clean_passes"] is True,
              "existing suite + generated patch is green on clean HEAD")
        if triage:
            check(total == triage["confirmed_real_gaps"],
                  "real-gap run starts from the confirmed detectable gaps only")
        check(f"{closed}/{total}" in readme or f"{closed}/{total}" in report,
              f"closure result {closed}/{total} appears in the writeup")

    # -- 6. evidence bundle -------------------------------------------------
    check_bundle(ROOT / "artifacts" / "bundle", "benchmark")
    check_bundle(ROOT / "artifacts" / "real-gap-bundle", "real-gap")

    # -- 6b. marginal-value audit ------------------------------------------
    audit = load(ROOT / "experiments" / "audit.json")
    if audit:
        for name, payload in audit.items():
            summary = payload["summary"]
            verdicts = summary["verdicts"]
            check(sum(verdicts.values()) == summary["tests_audited"],
                  f"audit[{name}]: every test received exactly one verdict",
                  f"{sum(verdicts.values())} == {summary['tests_audited']}")

            # A test may only be credited if it is green and stable.
            credited = [
                t for t in payload["tests"]
                if t["verdict"] != "HARMFUL" and t["faults_detected"] > 0
            ]
            check(all(t["green_on_clean"] and t["stable"] for t in credited),
                  f"audit[{name}]: only green, stable tests are credited")

            # VALUABLE must mean at least one uniquely detected fault.
            valuable = [t for t in payload["tests"] if t["verdict"] == "VALUABLE"]
            check(all(t["uniquely_detected"] > 0 for t in valuable),
                  f"audit[{name}]: every VALUABLE test has a unique detection")

            # UNPROVEN must mean zero detections.
            unproven = [t for t in payload["tests"] if t["verdict"] == "UNPROVEN"]
            check(all(t["faults_detected"] == 0 for t in unproven),
                  f"audit[{name}]: every UNPROVEN test detected nothing")

            mini = payload.get("minimization") or {}
            if mini:
                check(mini["kept_count"] <= mini["original_count"],
                      f"audit[{name}]: minimized patch is not larger")
                check(set(mini["novel_faults_after"]) == set(mini["novel_faults_before"]),
                      f"audit[{name}]: minimization preserves every novel fault",
                      f"{len(mini['novel_faults_after'])} of "
                      f"{len(mini['novel_faults_before'])}")
                check(mini["no_loss_verified"] is True,
                      f"audit[{name}]: no-loss claim was verified by re-execution")

    # -- 6c. counterexample search ------------------------------------------
    search = load(ROOT / "experiments" / "gap_search.json")
    if search:
        closed, total = search["gaps_closed"], search["confirmed_gaps"]
        check(abs(search["closure_rate"] - closed / total) < 1e-6,
              "search closure rate equals closed/confirmed", f"{closed}/{total}")
        check(search["model_calls"] == 0,
              "counterexample search made zero model calls")
        check(search["union_clean_passes"] is True,
              "existing suite + search patch is green on clean HEAD")
        if triage:
            check(total == triage["confirmed_real_gaps"],
                  "search runs on the confirmed detectable gaps only")
        actually = sum(1 for r in search["results"] if r.get("closed"))
        check(actually == closed,
              "reported closures match the per-gap records", f"{actually}")
        check(f"{closed}/{total}" in readme or f"{closed}/{total}" in report,
              f"search result {closed}/{total} appears in the writeup")

    # -- 7. no credentials --------------------------------------------------
    secret = re.compile(r"sk-[A-Za-z0-9_-]{15,}|BEGIN (?:RSA|OPENSSH) PRIVATE KEY")
    leaked = [
        p.name for p in ROOT.rglob("*")
        if p.is_file() and p.suffix in {".py", ".md", ".json", ".toml", ".lock"}
        and ".placebo-ws" not in str(p) and "subject" not in str(p)
        and secret.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    check(not leaked, "no credentials in the submission", ", ".join(leaked[:3]))

    # -- report -------------------------------------------------------------
    width = 74
    print("=" * width)
    print("  CONSISTENCY CHECK - every headline claim vs. its evidence")
    print("=" * width)
    failed = 0
    for ok, label in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        failed += 0 if ok else 1
    print("=" * width)
    print(f"  {len(checks) - failed}/{len(checks)} checks pass")
    if failed:
        print(f"  {failed} FAILED - the writeup contradicts the data")
    print("=" * width)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

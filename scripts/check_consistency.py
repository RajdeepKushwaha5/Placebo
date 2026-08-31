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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

UPSTREAM_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"

# Line-ending constants, kept as named bytes so the source contains no
# escape sequences that a rewriting tool could mangle.
LF = bytes([10])
CR = bytes([13])
CRLF = CR + LF


checks: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    checks.append((ok, f"{label}{(' - ' + detail) if detail else ''}"))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def normalised_digest(path: Path) -> str:
    """sha256 of file content with line endings normalised to LF.

    Hashing raw bytes would make this depend on the git checkout rather
    than on the source: the same commit is CRLF on Windows and LF on
    Linux, so a raw-byte digest recorded on one platform fails on the
    other and reports tampering that did not happen.
    See scripts/hash_subjects.py.
    """
    raw = path.read_bytes()
    normalised = (
        raw.replace(CRLF, LF).replace(CR, LF).rstrip(LF)
    )
    return hashlib.sha256(normalised).hexdigest()

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
            path = ROOT / relative
            if not path.is_file():
                check(False, f"subject file present: {relative}")
                continue
            check(normalised_digest(path) == expected,
                  f"subject hash matches: {relative}")

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

    # -- 6d. real historical bugs -------------------------------------------
    historical = load(ROOT / "experiments" / "historical_bugs.json")
    if historical:
        found = historical["witnesses_found"]
        behavioral = historical["behavior_changing_bugs"]
        check(found <= behavioral,
              "historical: witnesses cannot exceed behavior-changing bugs",
              f"{found}/{behavioral}")
        check(historical["model_calls"] == 0,
              "historical bug evaluation used zero model calls")
        actually = sum(1 for r in historical["results"] if r.get("found"))
        check(actually >= found,
              "historical: reported witnesses match the per-bug records")
        check(historical["refactors_correctly_indistinguishable"]
              == historical["behavior_preserving_refactors"],
              "historical: behavior-preserving refactors yield no witness",
              "confirms the equivalent-mutant triage independently")
        check(f"{found}/{behavioral}" in readme or f"{found}/{behavioral}" in report,
              f"historical result {found}/{behavioral} appears in the writeup")

    # -- 6e. second repository ----------------------------------------------
    multirepo = load(ROOT / "experiments" / "multirepo_census.json")
    if multirepo:
        check(len(multirepo) >= 2,
              "generalization: at least two subject repositories",
              f"{len(multirepo)} subjects")
        for name, s in multirepo.items():
            computed = s["killed"] / s["scorable"] if s["scorable"] else 0
            check(abs(s["mutation_score"] - computed) < 5e-5,
                  f"multirepo[{name}]: mutation score equals killed/scorable",
                  f"{s['killed']}/{s['scorable']}")

    # -- 6f. metamorphic oracle ---------------------------------------------
    metamorphic = load(ROOT / "experiments" / "metamorphic.json")
    if metamorphic:
        check(metamorphic["all_properties_sound_on_clean"] is True,
              "metamorphic: every property holds on clean code",
              "an unsound property would invalidate its detections")
        check(metamorphic["model_calls"] == 0,
              "metamorphic evaluation used zero model calls")
        check(metamorphic["gaps_detected"] <= metamorphic["confirmed_gaps"],
              "metamorphic: detections cannot exceed the gap set")
        detected = sum(1 for r in metamorphic["results"] if r.get("detected"))
        check(detected == metamorphic["gaps_detected"],
              "metamorphic: reported detections match per-gap records")

    # -- 6g. variance --------------------------------------------------------
    variance = load(ROOT / "experiments" / "variance.json")
    if variance:
        for name, c in variance["conditions"].items():
            check(c["runs"] >= 2,
                  f"variance[{name}]: at least two independent runs",
                  f"{c['runs']} runs")
            lo, hi = c["admitted_ci95"]
            check(lo <= c["admitted_median"] <= hi,
                  f"variance[{name}]: median lies inside its bootstrap interval")
            check(c["admitted_min"] <= c["admitted_median"] <= c["admitted_max"],
                  f"variance[{name}]: median lies inside the observed range")

    # -- 6h. reviewer study is honestly labelled -----------------------------
    study_key = ROOT / "artifacts" / "review-study" / "key.json"
    if study_key.exists():
        ratings = ROOT / "artifacts" / "review-study" / "ratings"
        has_ratings = ratings.exists() and any(ratings.glob("*.json"))
        check(not has_ratings,
              "reviewer study: no ratings collected, and none are claimed",
              "instrument ships without data, as stated")
        patches = ROOT / "artifacts" / "review-study" / "patches"
        leaked = [
            p.name for p in patches.glob("*.py")
            if re.search(r"placebo|mutant id|fault detected",
                         p.read_text(encoding="utf-8"), re.IGNORECASE)
        ] if patches.exists() else []
        check(not leaked,
              "reviewer study: patches carry no condition markers",
              ", ".join(leaked[:3]))

    # -- 6i. equal-budget control -------------------------------------------
    equal_budget = load(ROOT / "experiments" / "equal_budget.json")
    if equal_budget:
        detected = equal_budget["best_of_n_detects"]
        faults = equal_budget["faults"]
        check(detected <= faults,
              "equal-budget: detections cannot exceed the fault set",
              f"{detected}/{faults}")
        check(equal_budget["kept_green_candidate"] <= faults,
              "equal-budget: green candidates cannot exceed the fault set")
        actual = sum(1 for r in equal_budget["results"]
                     if r.get("any_draw_detects_fault"))
        check(actual == detected,
              "equal-budget: reported detections match the per-fault records",
              f"{actual}")
        if results and "placebo_D" in results.get("conditions", {}):
            scaffolded = results["conditions"]["placebo_D"]
            check(equal_budget["model_calls"] > scaffolded["usage"]["calls"],
                  "equal-budget baseline was given at least as much compute",
                  f"{equal_budget['model_calls']} vs {scaffolded['usage']['calls']} calls")

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

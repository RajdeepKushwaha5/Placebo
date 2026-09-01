"""Placebo command line.

The commands are named for the questions a reviewer actually asks:

    placebo audit    which of these tests earn their place?
    placebo gaps     what does my suite fail to detect?
    placebo explain  why does this specific test exist?
    placebo verify   can I re-check these claims myself?

Every command is read-only with respect to the repository under test. Nothing
here merges, rewrites production code, or acts without a human deciding to.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
TARGET_FILES = ["semver/version.py"]


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace) -> int:
    """Classify each test in a patch by its marginal fault-detection value."""
    from .audit.marginal import (
        audit_suite, minimal_patch, sample_fault_corpus,
    )
    from .mutation.engine import enumerate_subject
    from .verification.runner import SubjectRunner

    suite_path = Path(args.patch)
    if not suite_path.is_absolute():
        suite_path = ROOT / suite_path
    if not suite_path.exists():
        print(f"no such patch: {suite_path}")
        return 2

    census = _load(ROOT / "artifacts" / "census.json") or {}
    existing = {mid for mid, r in census.items() if r["status"] == "killed"}
    faults = enumerate_subject(ROOT / "subject", TARGET_FILES, SUBJECT_COMMIT)
    if args.faults:
        # Never truncate away the faults the existing suite misses: doing so
        # would report a gap-closing patch as detecting nothing novel.
        faults = sample_fault_corpus(faults, existing, args.faults)

    runner = SubjectRunner(ROOT / "subject", ROOT / ".placebo-ws" / "cli", timeout_s=60)
    runner.prepare()

    code = suite_path.read_text(encoding="utf-8")
    def show_progress(phase: str, current: int, total: int) -> None:
        print(f"\r    {phase:24s} {current:>3}/{total:<3}", end="", flush=True)

    print("\n  Running audit (first run is intentionally exhaustive):")
    audit = audit_suite(
        runner, suite_path.stem, code, faults, existing, progress=show_progress
    )
    print("\r" + " " * 48 + "\r", end="")
    summary = audit.summary()
    counts = summary["verdicts"]

    print(f"\n  {summary['tests_audited']} tests in {suite_path.name}, "
          f"audited against {summary['fault_corpus']} fault models\n")
    for record in audit.tests:
        print(f"    {record.verdict.value:24s} {record.name}")
    print()
    print(f"    {counts['VALUABLE']:>3} add unique fault detection the existing suite lacks")
    print(f"    {counts['REDUNDANT_WITH_SIBLING']:>3} duplicate a sibling test in this patch")
    print(f"    {counts['REDUNDANT_WITH_EXISTING']:>3} only re-detect what the repo already detects")
    print(f"    {counts['UNPROVEN']:>3} show no marginal sensitivity under these fault models")
    print(f"    {counts['HARMFUL']:>3} are red or unstable against correct code")
    print()
    print(f"    gaps closed by this patch : {summary['gaps_closed_by_patch']}")
    print(f"    review burden reduction   : {summary['review_burden_reduction']:.0%}")

    if args.minimize:
        minimized, kept, preserved = minimal_patch(audit, code)
        out = suite_path.with_suffix(".minimized.py")
        out.write_text(minimized or "# no tests carried measured novel value\n",
                       encoding="utf-8")
        print(f"\n    minimized patch -> {out.name} "
              f"({len(kept)} of {summary['tests_audited']} tests, "
              f"preserving {len(preserved)} measured novel faults)")
        if minimized and preserved:
            preserved_faults = [f for f in faults if f.id in preserved]
            recheck = audit_suite(
                runner,
                f"{suite_path.stem}.minimized",
                minimized,
                preserved_faults,
                existing,
                stability_repeats=1,
                progress=show_progress,
            )
            print("\r" + " " * 48 + "\r", end="")
            still_detected = {fault for test in recheck.tests for fault in test.novel}
            if still_detected != preserved:
                print("    minimized patch verification: FAILED")
                print(f"    lost faults: {sorted(preserved - still_detected)}")
                return 1
            print("    minimized patch verification: NO LOSS (re-executed)")
    print("\n  Human approval required before merging. Placebo proposes; it does not merge.\n")
    return 0


# --------------------------------------------------------------------------
# gaps
# --------------------------------------------------------------------------

def cmd_gaps(args: argparse.Namespace) -> int:
    """Report faults the existing suite does not detect."""
    census = _load(ROOT / "artifacts" / "census.json")
    summary = _load(ROOT / "artifacts" / "census_summary.json")
    triage = _load(ROOT / "artifacts" / "survivor_triage.json")
    if not census or not summary:
        print("no census found - run: python scripts/run_census.py")
        return 2

    from .mutation.engine import enumerate_subject
    faults = {m.id: m for m in enumerate_subject(ROOT / "subject", TARGET_FILES, SUBJECT_COMMIT)}
    survivors = [mid for mid, r in census.items() if r["status"] == "survived"]

    print(f"\n  Suite: {summary['scorable']} fault models evaluated")
    print(f"  Detected: {summary['killed']}  ({summary['mutation_score']:.1%})")
    print(f"  Undetected: {len(survivors)}\n")

    verdicts = {}
    if triage:
        verdicts = {f["id"]: f["verdict"] for f in triage.get("findings", [])}

    for mid in sorted(survivors):
        fault = faults.get(mid)
        if not fault:
            continue
        verdict = verdicts.get(mid, "UNTRIAGED")
        mark = "REAL GAP  " if verdict == "CONFIRMED_REAL_GAP" else "equivalent"
        print(f"    {mark}  {mid}  {fault.label}")
    print("\n  'equivalent' means no test can distinguish it - excluded from scoring.\n")
    return 0


# --------------------------------------------------------------------------
# explain
# --------------------------------------------------------------------------

def cmd_explain(args: argparse.Namespace) -> int:
    """Show the recorded evidence for one generated test."""
    bundle = ROOT / args.bundle
    tests = _load(bundle / "evidence" / "tests.json")
    if not tests:
        print(f"no evidence at {bundle}")
        return 2

    matches = [t for t in tests if args.test in t["test_name"]]
    if not matches:
        print(f"no test matching {args.test!r} in {bundle.name}")
        print("available:")
        for t in tests:
            print(f"    {t['test_name']}")
        return 1

    for entry in matches:
        fault = entry["detects_fault"]
        print(f"\n  {entry['test_name']}\n")
        print(f"    exists to detect : {fault['label']}")
        print(f"    location         : {fault['file']}:{fault['line']} in {fault['function']}")
        print(f"    fault id         : {fault['mutant_id']}")
        print("    the change it catches:")
        for line in fault["diff"].splitlines():
            print(f"        {line}")
        print(f"    verified by      : {', '.join(entry['proven_by']) or 'n/a'}")
        print(f"\n    {entry['claim']}\n")
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def cmd_verify(args: argparse.Namespace) -> int:
    """Re-execute every claim in an evidence bundle."""
    sys.argv = ["verify_bundle.py", "--bundle", args.bundle]
    sys.path.insert(0, str(ROOT / "scripts"))
    import verify_bundle  # noqa: PLC0415
    return verify_bundle.main()


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    """Report whether a repository can be audited, and what blocks it."""
    from .doctor import diagnose, init_config, render

    repo = Path(args.repo)
    if not repo.is_absolute():
        repo = (Path.cwd() / repo).resolve()

    if args.init:
        if not repo.is_dir():
            print(f"no such directory: {repo}")
            return 2
        print(init_config(repo))
        return 0

    report = diagnose(repo, quick=args.quick)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(render(report))

    # Non-zero exit so this can gate a pipeline.
    return 0 if report.supported else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="placebo",
        description="Audit the marginal fault-detection value of generated tests.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="classify tests in a patch by marginal value")
    p_audit.add_argument("patch", help="path to the test file to audit")
    p_audit.add_argument("--faults", type=int, default=0, help="cap the fault corpus")
    p_audit.add_argument("--minimize", action="store_true",
                         help="also write the smallest patch that loses no detection")
    p_audit.set_defaults(func=cmd_audit)

    p_gaps = sub.add_parser("gaps", help="list faults the existing suite misses")
    p_gaps.set_defaults(func=cmd_gaps)

    p_explain = sub.add_parser("explain", help="why does this generated test exist?")
    p_explain.add_argument("test", help="test name or substring")
    p_explain.add_argument("--bundle", default="artifacts/bundle")
    p_explain.set_defaults(func=cmd_explain)

    p_verify = sub.add_parser("verify", help="re-check every claim in a bundle")
    p_verify.add_argument("--bundle", default="artifacts/bundle")
    p_verify.set_defaults(func=cmd_verify)

    p_doctor = sub.add_parser(
        "doctor", help="can Placebo audit this repository, and if not why not?")
    p_doctor.add_argument("repo", help="path to the repository to check")
    p_doctor.add_argument("--init", action="store_true",
                          help="print a starting .placebo.toml inferred from the layout")
    p_doctor.add_argument("--quick", action="store_true",
                          help="skip running the existing test suite")
    p_doctor.add_argument("--json", action="store_true",
                          help="emit the report as JSON")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

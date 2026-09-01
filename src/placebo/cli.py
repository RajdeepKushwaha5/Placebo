"""Placebo command line.

The commands are named for the questions a reviewer actually asks:

    placebo doctor   can Placebo audit this repository, and if not why not?
    placebo census   which injected faults does the existing suite miss?
    placebo gaps     show me those misses
    placebo audit    which of these tests earn their place?
    placebo oracles  what does this repository already state about itself?
    placebo explain  why does this specific test exist?
    placebo verify   can I re-check these claims myself?

Each command takes the repository to work on and reads its `.placebo.toml`
contract, so nothing here is tied to a particular project. The vendored semver
subject is the default only so existing invocations keep working.

Every command is read-only with respect to the repository under test. Nothing
here merges, rewrites production code, or acts without a human deciding to.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]



def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None



DEFAULT_REPO = "subject"


def _resolve_repo(args: argparse.Namespace):
    """Load the repository contract named by --repo.

    Returns (config, census_dict, existing_kill_ids) or None after printing an
    actionable message. Census results are stored per repository so auditing a
    second project cannot silently reuse the first one's fault map.
    """
    from .config import ConfigError, load

    raw = getattr(args, "repo", None) or DEFAULT_REPO
    repo = Path(raw)
    if not repo.is_absolute():
        repo = (ROOT / repo) if (ROOT / repo).exists() else (Path.cwd() / repo)

    try:
        config = load(repo)
    except ConfigError as exc:
        print(f"  {exc}")
        print("  Run 'placebo doctor <repo>' for a full preflight.")
        return None

    census = _load(_census_path(config)) or {}
    existing = {mid for mid, r in census.items() if r.get("status") == "killed"}
    return config, census, existing


def _census_path(config) -> Path:
    """Where this repository's fault map lives.

    The original single-subject path is preserved so existing artifacts and
    every stored claim about them stay valid.
    """
    if config.name == "semver":
        return ROOT / "artifacts" / "census.json"
    return ROOT / "artifacts" / f"census_{config.name}.json"


def _select_sandbox(args, config):
    """Choose an execution backend and say which one, plainly.

    Isolation is preferred wherever it is available. Falling back to the host
    is allowed but never silent: repository tests and model-produced code would
    then run with this user's environment, credentials and network.
    """
    from .sandbox import Limits, SandboxUnavailable, select

    mode = "local" if getattr(args, "unsafe_local", False) else getattr(
        args, "sandbox", "auto")
    try:
        executor = select(
            mode,
            subject_root=config.root,
            limits=Limits(timeout_s=config.timeout_seconds),
        )
    except SandboxUnavailable as exc:
        print(f"\n  {exc}")
        return None

    if executor.isolated:
        described = executor.describe()
        print(f"\n  Sandbox: {described['image_digest']}")
        print(f"           network {described['network']}, read-only root, "
              f"limits {described['limits']['cpus']} cpu / "
              f"{described['limits']['memory']}")
    else:
        print("\n  Sandbox: NONE. Tests run on this host with your "
              "environment and network.")
    return executor


def _open_cache(config, enabled: bool = True):
    """Open this repository's execution cache.

    The fingerprint covers the interpreter, pytest, Placebo and the digest of
    every mutation target, so editing the subject invalidates the cache instead
    of serving results for code that no longer exists.
    """
    from .cache import NullCache, ResultCache, environment_fingerprint

    if not enabled:
        return NullCache()

    digests = {}
    for relative in config.resolved_targets():
        path = config.root / relative
        if path.is_file():
            raw = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            digests[relative] = hashlib.sha256(raw).hexdigest()

    fingerprint = environment_fingerprint(digests)
    cache = ResultCache(
        ROOT / ".placebo-cache" / f"{config.name}.sqlite", fingerprint
    )
    cache.prune_stale()
    return cache


def _triage_path(config) -> Path:
    """Where this repository's equivalence triage lives, if it has one."""
    if config.name == "semver":
        return ROOT / "artifacts" / "survivor_triage.json"
    return ROOT / "artifacts" / f"survivor_triage_{config.name}.json"


# --------------------------------------------------------------------------
# census
# --------------------------------------------------------------------------

def cmd_census(args: argparse.Namespace) -> int:
    """Build the fault map: which injected faults does the existing suite miss?"""
    from .config import ConfigError, load
    from .mutation.census import run_census
    from .mutation.engine import enumerate_subject
    from .verification.runner import allocate_workspace
    from .mutation.models import write_json

    repo = Path(args.repo)
    if not repo.is_absolute():
        repo = (ROOT / repo) if (ROOT / repo).exists() else (Path.cwd() / repo)
    try:
        config = load(repo)
    except ConfigError as exc:
        print(f"  {exc}")
        print("  Run 'placebo doctor <repo>' for a full preflight.")
        return 2

    targets = config.resolved_targets()
    if not targets:
        print(f"  No mutation targets resolved for '{config.name}'.")
        return 2

    faults = enumerate_subject(config.root, targets, config.commit or "working-tree")
    if args.faults:
        faults = faults[: args.faults]

    print(f"\n  {config.name}: {len(faults)} faults across "
          f"{len({m.qualname for m in faults})} functions")
    print(f"  Running the existing suite once per fault "
          f"({args.workers} workers). This is the slow, exhaustive pass.\n")

    try:
        census = run_census(config.root,
                            allocate_workspace(ROOT / ".placebo-ws",
                                               f"census-{config.name}",
                                               config.commit or "working-tree"),
                            faults, workers=args.workers,
                            timeout_s=config.timeout_seconds * 5,
                            source_roots=config.source_roots)
    except RuntimeError as exc:
        # The runner refuses to score faults when the clean suite is red.
        print(f"  {exc}".splitlines()[0])
        print("  A red suite makes every verdict meaningless. Fix it, then retry.")
        return 2

    summary = census.summary()
    out = _census_path(config)
    write_json(out, {mid: run.to_dict() for mid, run in sorted(census.runs.items())})

    print(f"  faults evaluated : {summary['scorable']}")
    print(f"  detected         : {summary['killed']}")
    print(f"  UNDETECTED       : {summary['survived']}")
    print(f"  mutation score   : {summary['mutation_score']:.1%}")
    print(f"  wall             : {summary['wall_s']}s")
    print(f"\n  fault map -> {out.relative_to(ROOT)}")
    print(f"  Next: placebo gaps --repo {args.repo}\n")
    return 0


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace) -> int:
    """Classify each test in a patch by its marginal fault-detection value."""
    from .audit.marginal import sample_fault_corpus
    from .mutation.engine import enumerate_subject

    suite_path = Path(args.patch)
    if not suite_path.is_absolute():
        suite_path = ROOT / suite_path
    if not suite_path.exists():
        print(f"no such patch: {suite_path}")
        return 2

    resolved = _resolve_repo(args)
    if resolved is None:
        return 2
    config, census, existing = resolved
    if not census:
        print(f"  No fault map for '{config.name}'. Run: placebo census {args.repo}")
        return 2
    faults = enumerate_subject(
        config.root, config.resolved_targets(), config.commit or "working-tree"
    )
    if args.faults:
        # Never truncate away the faults the existing suite misses: doing so
        # would report a gap-closing patch as detecting nothing novel.
        faults = sample_fault_corpus(faults, existing, args.faults)

    return _run_audit(
        args, config, existing, faults,
        name=suite_path.stem,
        label=suite_path.name,
        code=suite_path.read_text(encoding="utf-8"),
        minimized_path=suite_path.with_suffix(".minimized.py"),
    )


def _bar(current: int, total: int, width: int = 18) -> str:
    """A progress bar. Cheap, and it turns a number into a shape."""
    filled = int(width * current / total) if total else 0
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _clock(seconds: float) -> str:
    """Seconds as something a person reads at a glance."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _run_audit(args, config, existing, faults, name, label, code,
               minimized_path, scope_note: str = "") -> int:
    """Audit one patch and print the report. Shared by audit and audit-pr."""
    from .verification.runner import prune_workspaces

    # Sweep run directories abandoned by earlier crashes. Only leaves older
    # than a day are removed, so a concurrent run is never disturbed.
    prune_workspaces(ROOT / ".placebo-ws")

    store = _open_cache(config, enabled=not args.no_cache)
    try:
        return _audit_and_report(args, config, existing, faults, name, label,
                                 code, minimized_path, scope_note, store)
    finally:
        # Windows holds a lock while a sqlite connection is open, so a missed
        # close leaves the cache file undeletable for the next run.
        store.close()


def _audit_and_report(args, config, existing, faults, name, label, code,
                      minimized_path, scope_note, store) -> int:
    from .audit.marginal import AUDIT_PATH, audit_suite, minimal_patch
    from .verification.runner import SubjectRunner, allocate_workspace

    executor = _select_sandbox(args, config)
    if executor is None:
        return 2

    # Every run gets its own workspace. Sharing one per repository meant a
    # second concurrent run deleted this one's subject files mid-audit.
    runner = SubjectRunner(
        config.root,
        allocate_workspace(ROOT / ".placebo-ws", config.name,
                           config.commit or "working-tree"),
        timeout_s=config.timeout_seconds,
        source_roots=config.source_roots,
        executor=executor,
    )
    runner.prepare()

    # A verdict only means something if the suite can run at all. Without this,
    # a sandbox whose image lacks pytest reports every test as red against
    # correct code, which reads as a finding and is really a broken
    # environment. The census already refused on a red baseline; the audit is
    # the path where a wrong answer would actually be believed.
    baseline = runner.check_baseline()
    if not baseline.passed:
        print("\n  The subject's own suite is not green here, so no verdict "
              "would mean anything.")
        combined = baseline.stderr + baseline.stdout
        if "No module named pytest" in combined:
            print("  pytest is not available in the chosen environment.")
            if runner.executor.isolated:
                print("  Build the runner image (docs/SANDBOX.md), or pass "
                      "--unsafe-local to run on this host instead.")
        elif baseline.collection_broken:
            print("  pytest could not collect the suite. Usually the subject "
                  "is not importable: check source_roots in .placebo.toml.")
        elif baseline.timed_out:
            print("  The suite timed out. Raise timeout_seconds in .placebo.toml.")
        else:
            print("  Fix the failing tests, then retry.")
        for line in (baseline.stdout or baseline.stderr).strip().splitlines()[-3:]:
            print(f"    {line}")
        runner.cleanup()
        return 2

    started_at = time.perf_counter()
    phase_started: dict[str, float] = {}

    def show_progress(phase: str, current: int, total: int) -> None:
        """One line, overwritten, carrying a rate and an estimate.

        A bare counter tells you it is alive. What a user actually wants to
        know is whether to wait, so the remaining time is shown once enough
        items have completed for the rate to mean anything.
        """
        now = time.perf_counter()
        begun = phase_started.setdefault(phase, now)
        elapsed = now - begun
        suffix = ""
        if current >= 3 and elapsed > 1:
            rate = current / elapsed
            remaining = (total - current) / rate if rate else 0
            suffix = f"  {rate:4.1f}/s  eta {_clock(remaining)}"
        bar = _bar(current, total)
        print(f"\r    {phase:24s} {bar} {current:>4}/{total:<4}{suffix}   ",
              end="", flush=True)

    commit = config.commit or "working-tree"
    coverage_map = None
    if not args.no_select:
        from .evaluation.repair import split_tests
        from .selection import load_or_build_coverage_map

        _preamble, patch_tests = split_tests(code)
        coverage_map = load_or_build_coverage_map(
            runner, store, commit, AUDIT_PATH, code,
            {name for name, _src in patch_tests}, list(config.import_names),
        )
        if coverage_map.complete:
            saved = coverage_map.reduction(faults)
            print(f"\n  Coverage map: {coverage_map.to_dict()['attributed_lines']} "
                  f"attributed lines, avoiding {saved:.0%} of test executions")
        else:
            print("\n  Coverage map unavailable; auditing exhaustively.")

    warm = store.entries()
    if warm:
        print(f"\n  Running audit ({warm} cached executions available):")
    else:
        print("\n  Running audit (first run is intentionally exhaustive):")
    pool = [runner]
    requested = max(1, int(getattr(args, "workers", 1) or 1))
    for _ in range(requested - 1):
        extra = SubjectRunner(
            config.root,
            allocate_workspace(ROOT / ".placebo-ws", config.name,
                               config.commit or "working-tree"),
            timeout_s=config.timeout_seconds,
            source_roots=config.source_roots,
            executor=runner.executor,
        )
        extra.prepare()
        pool.append(extra)
    if len(pool) > 1:
        print(f"  Workers: {len(pool)}, each in its own workspace")

    try:
        audit = audit_suite(
            runner, name, code, faults, existing, progress=show_progress,
            cache=store, subject_commit=commit, coverage_map=coverage_map,
            budget_s=args.budget or None,
            workers=pool if len(pool) > 1 else None,
        )
    finally:
        for extra in pool[1:]:
            extra.cleanup()
    print("\r" + " " * 48 + "\r", end="")
    summary = audit.summary()
    counts = summary["verdicts"]

    print(f"\n  {summary['tests_audited']} tests in {label}, "
          f"audited against {summary['fault_corpus']} fault models")
    if scope_note:
        print(f"  {scope_note}")
    print()
    for record in audit.tests:
        print(f"    {record.verdict.value:24s} {record.name}")
    print()
    print(f"    {counts['VALUABLE']:>3} add unique fault detection the existing suite lacks")
    print(f"    {counts['REDUNDANT_WITH_SIBLING']:>3} duplicate a sibling test in this patch")
    print(f"    {counts['REDUNDANT_WITH_EXISTING']:>3} only re-detect what the repo already detects")
    print(f"    {counts['UNPROVEN']:>3} show no marginal sensitivity under these fault models")
    print(f"    {counts['HARMFUL']:>3} are red or unstable against correct code")
    print()
    if summary.get("budget_exhausted"):
        print(f"    PARTIAL: the {args.budget}s budget stopped the audit after "
              f"{summary['faults_evaluated']} of {summary['fault_corpus']} faults "
              f"({summary['corpus_coverage']:.0%} of the corpus).")
        print("    UNPROVEN below means 'not shown within the budget'.")
        print()
    if summary.get("faults_skipped_by_selection"):
        print(f"    {summary['faults_skipped_by_selection']:>3} faults no test in "
              f"this patch can reach (not executed)")
        print()
    print(f"    gaps closed by this patch : {summary['gaps_closed_by_patch']}")
    print(f"    review burden reduction   : {summary['review_burden_reduction']:.0%}")

    # Oracle strength is a separate axis from marginal value. A test can be the
    # sole detector of a real fault and still only pin current behaviour, so the
    # two are reported side by side rather than combined into one score.
    from .oracle import report_suite, summarise as summarise_oracles

    oracles = report_suite(code)
    if oracles:
        levels = summarise_oracles(oracles)
        print()
        print("    oracle strength:")
        for label, count in levels["by_level"].items():
            if count:
                print(f"      {count:>3} {label}")
        if levels["snapshot_only"]:
            print(f"      {levels['snapshot_only']} test(s) record current behaviour "
                  f"rather than verified correctness.")
        if levels["brittle"]:
            print(f"      {levels['brittle']} test(s) carry {levels['warnings']} "
                  f"brittleness warning(s):")
            kinds: dict[str, int] = {}
            for report in oracles:
                for warning in report.warnings:
                    kinds[warning.kind] = kinds.get(warning.kind, 0) + 1
            for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
                print(f"        {count:>3} {kind}")

    if args.minimize:
        minimized, kept, preserved = minimal_patch(audit, code)
        out = minimized_path
        out.write_text(minimized or "# no tests carried measured novel value\n",
                       encoding="utf-8")
        print(f"\n    minimized patch -> {out.name} "
              f"({len(kept)} of {summary['tests_audited']} tests, "
              f"preserving {len(preserved)} measured novel faults)")
        if minimized and preserved:
            preserved_faults = [f for f in faults if f.id in preserved]
            recheck = audit_suite(
                runner,
                f"{name}.minimized",
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

    if args.sarif:
        from .sarif import build as build_sarif

        document = build_sarif(
            audit, code, label,
            oracles=oracles,
            include_snapshot_notes=args.sarif_oracle_notes,
        )
        document["runs"][0]["invocations"][0]["properties"]["sandbox"] = (
            runner.executor.describe())
        out_path = Path(args.sarif)
        if not out_path.is_absolute():
            out_path = Path.cwd() / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        findings = len(document["runs"][0]["results"])
        print(f"\n    SARIF -> {out_path.name} ({findings} finding(s))")

    stats = store.stats()
    if stats.lookups:
        print(f"\n    cache: {stats.hits} reused, {stats.misses} executed "
              f"({stats.hit_rate:.0%} reused)")
    print("\n  Human approval required before merging. Placebo proposes; it does not merge.\n")
    return 0


# --------------------------------------------------------------------------
# audit-pr
# --------------------------------------------------------------------------

def cmd_audit_pr(args: argparse.Namespace) -> int:
    """Audit only the tests a diff adds or changes.

    A reviewer looking at a pull request is deciding about that diff, not about
    the repository, so this scopes both sides of the question: the tests come
    from the diff, and the fault corpus is narrowed to the source lines the
    diff touched. The scope is printed with the verdicts, because "UNPROVEN
    against 12 faults from one file" is a different statement from "UNPROVEN
    against the full corpus".
    """
    from .diff import (
        changed_test_functions, extract_tests, parse_unified_diff, scope_faults,
    )
    from .mutation.engine import enumerate_subject

    if args.diff == "-":
        text = sys.stdin.read()
        source = "stdin"
    else:
        diff_path = Path(args.diff)
        if not diff_path.is_absolute():
            diff_path = Path.cwd() / diff_path
        if not diff_path.is_file():
            print(f"  no such diff: {diff_path}")
            print("  Pass a unified diff file, or '-' to read one from stdin.")
            return 2
        text = diff_path.read_text(encoding="utf-8", errors="replace")
        source = diff_path.name

    resolved = _resolve_repo(args)
    if resolved is None:
        return 2
    config, census, existing = resolved

    # Diagnose the diff before demanding a fault map. A malformed diff, or one
    # that touches no test, is knowable without a census, and reporting the
    # census first would name the wrong problem.
    diff = parse_unified_diff(text)
    if not diff.files:
        print(f"  {source} contains no recognisable file changes.")
        return 2

    selections = changed_test_functions(diff, config.root, config.test_roots)
    if not selections:
        print(f"\n  {source}: {len(diff.files)} file(s) changed, no test "
              f"functions added or modified.")
        print("  Nothing to audit. A diff that changes no test needs no test audit.\n")
        return 0

    code = extract_tests(config.root, selections)
    if not code:
        print("  Changed tests were found but could not be extracted.")
        return 2

    if not census:
        print(f"  No fault map for '{config.name}'. Run: placebo census {args.repo}")
        return 2

    faults = enumerate_subject(
        config.root, config.resolved_targets(), config.commit or "working-tree"
    )
    total = len(faults)
    faults = scope_faults(faults, diff, config.test_roots)

    changed = sum(len(names) for names in selections.values())
    print(f"\n  {source}: {changed} changed test(s) across "
          f"{len(selections)} file(s)")
    for path in sorted(selections):
        print(f"    {path}: {', '.join(selections[path])}")

    if len(faults) < total:
        note = (f"scope: {len(faults)} of {total} faults, limited to source "
                f"lines this diff touched")
    else:
        note = f"scope: the full corpus of {total} faults (no source file changed)"

    return _run_audit(
        args, config, existing, faults,
        name="pr",
        label=source,
        code=code,
        minimized_path=ROOT / "artifacts" / "pr.minimized.py",
        scope_note=note,
    )


# --------------------------------------------------------------------------
# oracles
# --------------------------------------------------------------------------

def cmd_oracles(args: argparse.Namespace) -> int:
    """Report the oracles a repository already states, strongest first.

    Every test Placebo generates is L4, because its expected values come from
    running the implementation. This finds the places where the repository has
    already said what it intends, so an assertion can cite a source instead of
    inventing an answer.
    """
    from .sourcing import source_oracles

    resolved = _resolve_repo(args)
    if resolved is None:
        return 2
    config, _census, _existing = resolved

    targets = [config.root / t for t in config.resolved_targets()]
    report = source_oracles(targets)

    if not report.candidates:
        print()
        print(f"  {config.name}: no documented examples in "
              f"{len(targets)} mutation target(s).")
        print("  Every generated assertion here would be an L4 snapshot: it")
        print("  records current behaviour, not intended behaviour.")
        print()
        return 0

    print()
    print(f"  {config.name}: {len(report.candidates)} oracle(s) sourced from "
          f"the repository's own documentation")
    print()
    for label, count in report.by_level().items():
        if count:
            print(f"    {count:>3} {label}")
    print()

    for candidate in report.candidates[: args.limit]:
        print(f"    {candidate.source}")
        print(f"      {candidate.expression}")
        first = candidate.expected.splitlines()[0]
        print(f"      -> {first[:64]}")
    if len(report.candidates) > args.limit:
        print(f"    ... {len(report.candidates) - args.limit} more")

    print()
    print("  These are claims the authors made, not values Placebo observed.")
    print("  A generated test citing one says where its answer came from.")
    print()

    if args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = Path.cwd() / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"  written -> {out.name}")
        print()
    return 0


# --------------------------------------------------------------------------
# gaps
# --------------------------------------------------------------------------

def cmd_gaps(args: argparse.Namespace) -> int:
    """Report faults the existing suite does not detect."""
    resolved = _resolve_repo(args)
    if resolved is None:
        return 2
    config, census, _existing = resolved
    if not census:
        print(f"  No fault map for '{config.name}'. Run: placebo census {args.repo}")
        return 2

    # Derive the summary from this repository's own census. Reading the stored
    # summary unconditionally would report semver's numbers for every project.
    scorable = sum(1 for r in census.values()
                   if r.get("status") in ("killed", "survived"))
    killed = sum(1 for r in census.values() if r.get("status") == "killed")
    summary = {
        "scorable": scorable,
        "killed": killed,
        "mutation_score": killed / scorable if scorable else 0.0,
    }
    # Triage verdicts are recorded per repository; absent means untriaged.
    triage = _load(_triage_path(config))

    from .mutation.engine import enumerate_subject
    faults = {
        m.id: m for m in enumerate_subject(
            config.root, config.resolved_targets(), config.commit or "working-tree"
        )
    }
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
        # Untriaged is not the same as equivalent. Reporting an unexamined
        # survivor as "no test can distinguish it" would assert something
        # nobody checked.
        mark = {
            "CONFIRMED_REAL_GAP": "REAL GAP  ",
            "EQUIVALENT_OR_CONTRACT_ONLY": "equivalent",
        }.get(verdict, "untriaged ")
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
    p_audit.add_argument("--repo", default=DEFAULT_REPO,
                         help="repository to audit against (needs .placebo.toml)")
    p_audit.add_argument("--faults", type=int, default=0, help="cap the fault corpus")
    p_audit.add_argument("--no-cache", action="store_true",
                         help="re-execute everything, ignoring recorded results")
    p_audit.add_argument("--no-select", action="store_true",
                         help="skip coverage-based selection and audit exhaustively")
    p_audit.add_argument("--sandbox", choices=("auto", "docker", "local"),
                         default="auto",
                         help="execution isolation; auto prefers a container")
    p_audit.add_argument("--unsafe-local", action="store_true",
                         help="run on this host with no boundary, inheriting your "
                              "environment, credentials and network")
    p_audit.add_argument("--workers", type=int, default=1,
                         help="run the fault matrix across N workers")
    p_audit.add_argument("--budget", type=float, default=0,
                         help="stop after N seconds and report partial evidence")
    p_audit.add_argument("--sarif", metavar="PATH",
                         help="write findings as SARIF for code-scanning annotations")
    p_audit.add_argument("--sarif-oracle-notes", action="store_true",
                         help="also annotate every snapshot-oracle test in the SARIF output")
    p_audit.add_argument("--minimize", action="store_true",
                         help="also write the smallest patch that loses no detection")
    p_audit.set_defaults(func=cmd_audit)

    p_pr = sub.add_parser("audit-pr",
                          help="audit only the tests a diff adds or changes")
    p_pr.add_argument("diff", help="unified diff file, or '-' for stdin")
    p_pr.add_argument("--repo", default=DEFAULT_REPO,
                      help="repository to audit against (needs .placebo.toml)")
    p_pr.add_argument("--faults", type=int, default=0, help="cap the fault corpus")
    p_pr.add_argument("--no-cache", action="store_true",
                      help="re-execute everything, ignoring recorded results")
    p_pr.add_argument("--no-select", action="store_true",
                      help="skip coverage-based selection and audit exhaustively")
    p_pr.add_argument("--sandbox", choices=("auto", "docker", "local"),
                      default="auto",
                      help="execution isolation; auto prefers a container")
    p_pr.add_argument("--unsafe-local", action="store_true",
                      help="run on this host with no boundary, inheriting your "
                           "environment, credentials and network")
    p_pr.add_argument("--workers", type=int, default=1,
                      help="run the fault matrix across N workers")
    p_pr.add_argument("--budget", type=float, default=0,
                      help="stop after N seconds and report partial evidence")
    p_pr.add_argument("--sarif", metavar="PATH",
                      help="write findings as SARIF for code-scanning annotations")
    p_pr.add_argument("--sarif-oracle-notes", action="store_true",
                      help="also annotate every snapshot-oracle test in the SARIF output")
    p_pr.add_argument("--minimize", action="store_true",
                      help="also write the smallest patch that loses no detection")
    p_pr.set_defaults(func=cmd_audit_pr)

    p_oracles = sub.add_parser(
        "oracles", help="what does this repository already state about itself?")
    p_oracles.add_argument("--repo", default=DEFAULT_REPO,
                           help="repository to inspect (needs .placebo.toml)")
    p_oracles.add_argument("--limit", type=int, default=8,
                           help="how many candidates to print")
    p_oracles.add_argument("--json", metavar="PATH",
                           help="write the full report")
    p_oracles.set_defaults(func=cmd_oracles)

    p_gaps = sub.add_parser("gaps", help="list faults the existing suite misses")
    p_gaps.add_argument("--repo", default=DEFAULT_REPO,
                        help="repository to report on (needs .placebo.toml)")
    p_gaps.set_defaults(func=cmd_gaps)

    p_census = sub.add_parser(
        "census", help="build the fault map for a repository")
    p_census.add_argument("repo", nargs="?", default=DEFAULT_REPO,
                          help="repository to census (needs .placebo.toml)")
    p_census.add_argument("--workers", type=int, default=4)
    p_census.add_argument("--faults", type=int, default=0,
                          help="cap the fault corpus for a quick pass")
    p_census.set_defaults(func=cmd_census)

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

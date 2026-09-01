"""Two Placebo runs against one repository must not interfere.

This is a regression test for a defect that was hit rather than imagined.
Workspaces were named after the repository, so a second run's `prepare()`
deleted the first run's subject files mid-audit. It surfaced as a
`FileNotFoundError` on a source file, which reads like a corrupted checkout
and sends you looking in the wrong place entirely.

The four properties asserted here are the ones that were violated:

  * neither workspace is deleted while the other run is using it
  * neither run's results are contaminated by the other
  * both caches stay valid and usable afterwards
  * cleanup removes the owning run's directory and nothing else
"""

from __future__ import annotations

import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.cache import ResultCache  # noqa: E402
from placebo.verification.runner import (  # noqa: E402
    SubjectRunner,
    allocate_workspace,
    prune_workspaces,
)

COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"

OPS = textwrap.dedent("""\
    def add(a, b):
        return a + b
    """)

SUITE = textwrap.dedent("""\
    from pkg.ops import add


    def test_add():
        assert add(2, 3) == 5
    """)


@pytest.fixture
def subject(tmp_path) -> Path:
    root = tmp_path / "subject"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "ops.py").write_text(OPS, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_ops.py").write_text(SUITE, encoding="utf-8")
    return root


# -- path allocation -------------------------------------------------------


def test_two_runs_never_receive_the_same_directory(tmp_path):
    paths = {
        allocate_workspace(tmp_path, "semver", COMMIT) for _ in range(50)
    }
    assert len(paths) == 50


def test_the_layout_separates_repository_then_commit_then_run(tmp_path):
    path = allocate_workspace(tmp_path, "semver", COMMIT)
    assert path.parent.parent.name == "semver"
    assert path.parent.name == COMMIT[:12]
    assert path.relative_to(tmp_path).parts[:2] == ("semver", COMMIT[:12])


def test_different_commits_of_one_repository_are_separated(tmp_path):
    a = allocate_workspace(tmp_path, "semver", "a" * 40)
    b = allocate_workspace(tmp_path, "semver", "b" * 40)
    assert a.parent != b.parent


def test_a_working_tree_with_no_commit_still_gets_a_path(tmp_path):
    path = allocate_workspace(tmp_path, "semver", "")
    assert path.parent.name == "working-tree"


def test_unsafe_characters_do_not_escape_the_base_directory(tmp_path):
    """A repository name is configuration, so it must not become a path."""
    path = allocate_workspace(tmp_path, "../../etc", "../../passwd")
    assert tmp_path.resolve() in path.resolve().parents


def test_an_explicit_run_id_is_honoured(tmp_path):
    path = allocate_workspace(tmp_path, "semver", COMMIT, run_id="fixed")
    assert path.name == "fixed"


# -- the four properties ---------------------------------------------------


def test_concurrent_runs_do_not_delete_each_others_workspace(subject, tmp_path):
    """Property 1. A second run preparing must not destroy the first's tree.

    Checking that the subject files exist is not enough: a shared workspace is
    deleted and immediately recopied, so the files are back before anyone
    looks. Each run therefore leaves a marker only it wrote, and the ordering
    is forced so the second prepare definitely happens after the first marker
    exists. A shared workspace takes that marker with it.
    """
    base = tmp_path / "ws"
    errors: list[BaseException] = []
    survived: dict[str, bool] = {}
    first_ready = threading.Event()
    second_prepared = threading.Event()

    def run(tag: str, is_first: bool) -> None:
        try:
            runner = SubjectRunner(
                subject, allocate_workspace(base, "pkg", COMMIT),
                source_roots=("pkg",),
            )
            if not is_first:
                assert first_ready.wait(timeout=60), "the first run never started"

            runner.prepare()
            marker = runner.workspace / f".marker-{tag}"
            marker.write_text(tag, encoding="utf-8")

            if is_first:
                first_ready.set()
                assert second_prepared.wait(timeout=60), "the second run never prepared"
            else:
                second_prepared.set()

            survived[tag] = marker.is_file() and marker.read_text(encoding="utf-8") == tag
            runner.cleanup()
        except BaseException as exc:  # noqa: BLE001 - reported to the assertion
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=("first", True)),
        threading.Thread(target=run, args=("second", False)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not errors, f"a concurrent run raised: {errors[0]!r}"
    assert survived == {"first": True, "second": True}, \
        "a run's workspace was destroyed while it was still using it"


def test_concurrent_runs_do_not_contaminate_each_others_results(subject, tmp_path):
    """Property 2. One run mutates its copy; the other must not see it."""
    base = tmp_path / "ws"
    seen: dict[str, str] = {}
    errors: list[BaseException] = []
    ready = threading.Barrier(2, timeout=60)

    def run(tag: str, mutate: bool) -> None:
        try:
            runner = SubjectRunner(
                subject, allocate_workspace(base, "pkg", COMMIT),
                source_roots=("pkg",),
            )
            runner.prepare()
            target = runner.workspace / "pkg" / "ops.py"
            if mutate:
                target.write_text(OPS.replace("a + b", "a - b"), encoding="utf-8")
            ready.wait()
            time.sleep(0.05)
            seen[tag] = target.read_text(encoding="utf-8")
            runner.cleanup()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=("mutating", True)),
        threading.Thread(target=run, args=("clean", False)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not errors, f"a concurrent run raised: {errors[0]!r}"
    assert "a - b" in seen["mutating"], "the mutating run lost its own change"
    assert "a + b" in seen["clean"], "the clean run saw another run's mutation"


def test_both_caches_stay_valid_after_concurrent_use(tmp_path):
    """Property 3. The cache is content-addressed, so concurrent writers must
    not corrupt it or invalidate each other's entries."""
    path = tmp_path / "shared.sqlite"
    errors: list[BaseException] = []
    written = 40

    def writer(prefix: str) -> None:
        try:
            with ResultCache(path, "fp") as cache:
                for i in range(written):
                    cache.put(cache.key("c", f"{prefix}{i}", "patch"),
                              {"status": "killed", "who": prefix})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(p,)) for p in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not errors, f"a concurrent cache writer raised: {errors[0]!r}"
    with ResultCache(path, "fp") as cache:
        for prefix in ("a", "b"):
            for i in range(written):
                entry = cache.get(cache.key("c", f"{prefix}{i}", "patch"))
                assert entry == {"status": "killed", "who": prefix}, \
                    f"{prefix}{i} was lost or overwritten by the other writer"


def test_cleanup_removes_only_the_owning_run(subject, tmp_path):
    """Property 4. Tearing one run down must leave every other run intact."""
    base = tmp_path / "ws"
    runners = []
    for _ in range(3):
        runner = SubjectRunner(subject, allocate_workspace(base, "pkg", COMMIT),
                               source_roots=("pkg",))
        runner.prepare()
        runners.append(runner)

    victim, survivors = runners[0], runners[1:]
    victim.cleanup()

    assert not victim.workspace.exists()
    for survivor in survivors:
        assert (survivor.workspace / "pkg" / "ops.py").is_file(), \
            "cleaning one run removed another run's files"
    # The shared parent is left alone: other runs may still be using it.
    assert victim.workspace.parent.is_dir()

    for survivor in survivors:
        survivor.cleanup()


def test_the_runner_cleans_up_when_used_as_a_context_manager(subject, tmp_path):
    base = tmp_path / "ws"
    with SubjectRunner(subject, allocate_workspace(base, "pkg", COMMIT),
                       source_roots=("pkg",)) as runner:
        workspace = runner.workspace
        assert (workspace / "pkg" / "ops.py").is_file()
    assert not workspace.exists()


# -- sweeping after a crash ------------------------------------------------


def test_pruning_removes_abandoned_runs_but_not_fresh_ones(subject, tmp_path):
    """A crashed run leaves its directory behind. A live one must survive."""
    import os

    base = tmp_path / "ws"
    stale = allocate_workspace(base, "pkg", COMMIT)
    stale.mkdir(parents=True)
    (stale / "marker").write_text("x", encoding="utf-8")
    old = time.time() - (48 * 3600)
    os.utime(stale, (old, old))

    fresh = allocate_workspace(base, "pkg", COMMIT)
    fresh.mkdir(parents=True)
    (fresh / "marker").write_text("x", encoding="utf-8")

    removed = prune_workspaces(base, max_age_hours=24)

    assert stale in removed and not stale.exists()
    assert fresh.exists(), "a run started minutes ago must not be swept"


def test_pruning_a_missing_directory_is_not_an_error(tmp_path):
    assert prune_workspaces(tmp_path / "absent") == []


def test_pruning_leaves_the_repository_and_commit_levels_alone(subject, tmp_path):
    import os

    base = tmp_path / "ws"
    run = allocate_workspace(base, "pkg", COMMIT)
    run.mkdir(parents=True)
    old = time.time() - (48 * 3600)
    os.utime(run, (old, old))

    prune_workspaces(base, max_age_hours=24)
    assert run.parent.is_dir(), "another run may still be using this commit level"

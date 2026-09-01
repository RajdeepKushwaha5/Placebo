"""Tests for the persistent result cache.

The cache exists to make a re-audit fast. It must never make one wrong, so
most of these tests are about refusing to answer rather than answering: every
input that could change an execution's outcome has to either be in the key or
in the fingerprint, and missing one would show up here as a stale hit.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.cache import (  # noqa: E402
    NullCache,
    ResultCache,
    environment_fingerprint,
)

PAYLOAD = {"status": "killed", "failing_tests": ["t.py::test_a"]}


def cache(tmp_path, fingerprint="fp") -> ResultCache:
    return ResultCache(tmp_path / "c.sqlite", fingerprint)


# -- round trip ------------------------------------------------------------


def test_stores_and_returns_a_payload(tmp_path):
    with cache(tmp_path) as c:
        key = c.key("commit", "fault", "patch")
        assert c.get(key) is None
        c.put(key, PAYLOAD)
        assert c.get(key) == PAYLOAD


def test_survives_reopening(tmp_path):
    """Resume after interruption depends on this."""
    path = tmp_path / "c.sqlite"
    with ResultCache(path, "fp") as c:
        c.put(c.key("commit", "fault", "patch"), PAYLOAD)
    with ResultCache(path, "fp") as c:
        assert c.get(c.key("commit", "fault", "patch")) == PAYLOAD


def test_counts_hits_and_misses(tmp_path):
    with cache(tmp_path) as c:
        key = c.key("commit", "fault", "patch")
        c.get(key)
        c.put(key, PAYLOAD)
        c.get(key)
        c.get(key)
        stats = c.stats()
        assert (stats.hits, stats.misses, stats.writes) == (2, 1, 1)
        assert stats.hit_rate == 2 / 3
        assert stats.to_dict()["hit_rate"] == 0.6667


# -- the key must separate anything that changes the outcome ---------------


def test_a_different_fault_does_not_hit(tmp_path):
    with cache(tmp_path) as c:
        c.put(c.key("commit", "fault_a", "patch"), PAYLOAD)
        assert c.get(c.key("commit", "fault_b", "patch")) is None


def test_an_edited_patch_does_not_hit(tmp_path):
    """Editing one test invalidates that patch's column. Missing this would
    report a verdict for code the user has already changed."""
    with cache(tmp_path) as c:
        c.put(c.key("commit", "fault", c.hash_patch("def test_a(): assert 1")), PAYLOAD)
        stale = c.key("commit", "fault", c.hash_patch("def test_a(): assert 0"))
        assert c.get(stale) is None


def test_a_different_subject_commit_does_not_hit(tmp_path):
    with cache(tmp_path) as c:
        c.put(c.key("commit_a", "fault", "patch"), PAYLOAD)
        assert c.get(c.key("commit_b", "fault", "patch")) is None


def test_a_different_test_selection_does_not_hit(tmp_path):
    """Running a subset can only observe the subset, so a result recorded for
    one selection is not evidence about another."""
    with cache(tmp_path) as c:
        c.put(c.key("c", "f", "p", ["tests/a.py"]), PAYLOAD)
        assert c.get(c.key("c", "f", "p", ["tests/a.py", "tests/b.py"])) is None


def test_selection_order_does_not_matter(tmp_path):
    """The same set of files is the same execution, however it was ordered."""
    with cache(tmp_path) as c:
        c.put(c.key("c", "f", "p", ["b.py", "a.py"]), PAYLOAD)
        assert c.get(c.key("c", "f", "p", ["a.py", "b.py"])) == PAYLOAD


def test_patch_hash_ignores_line_endings(tmp_path):
    """Otherwise a Windows checkout could never reuse a Linux entry, and the
    cache would silently do nothing on one of the two."""
    with cache(tmp_path) as c:
        assert c.hash_patch("a\r\nb\r\n") == c.hash_patch("a\nb\n")


# -- the fingerprint must invalidate everything else -----------------------

def test_a_changed_environment_invalidates_every_entry(tmp_path):
    path = tmp_path / "c.sqlite"
    with ResultCache(path, "fp_old") as c:
        c.put(c.key("commit", "fault", "patch"), PAYLOAD)
    with ResultCache(path, "fp_new") as c:
        assert c.get(c.key("commit", "fault", "patch")) is None
        assert c.entries() == 0, "old entries are unreadable, not merely ignored"


def test_fingerprint_moves_with_the_subject_source(tmp_path):
    """A dirty working tree is the same commit with different code."""
    a = environment_fingerprint({"pkg/m.py": "digest_a"})
    b = environment_fingerprint({"pkg/m.py": "digest_b"})
    assert a != b


def test_fingerprint_is_stable_for_identical_input():
    files = {"pkg/m.py": "d1", "pkg/n.py": "d2"}
    assert environment_fingerprint(files) == environment_fingerprint(dict(files))


def test_fingerprint_ignores_subject_file_ordering():
    assert environment_fingerprint({"a": "1", "b": "2"}) == environment_fingerprint(
        {"b": "2", "a": "1"}
    )


def test_pruning_removes_only_unreadable_entries(tmp_path):
    path = tmp_path / "c.sqlite"
    with ResultCache(path, "fp_old") as c:
        c.put(c.key("c", "f1", "p"), PAYLOAD)
    with ResultCache(path, "fp_new") as c:
        c.put(c.key("c", "f2", "p"), PAYLOAD)
        assert c.prune_stale() == 1
        assert c.entries() == 1
        assert c.get(c.key("c", "f2", "p")) == PAYLOAD


def test_clear_empties_the_cache(tmp_path):
    with cache(tmp_path) as c:
        c.put(c.key("c", "f", "p"), PAYLOAD)
        c.clear()
        assert c.entries() == 0


def test_overwriting_a_key_keeps_one_entry(tmp_path):
    with cache(tmp_path) as c:
        key = c.key("c", "f", "p")
        c.put(key, {"status": "survived"})
        c.put(key, {"status": "killed"})
        assert c.entries() == 1
        assert c.get(key) == {"status": "killed"}


def test_creates_its_parent_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "c.sqlite"
    with ResultCache(nested, "fp"):
        assert nested.exists()


# -- the disabled cache behaves like an empty one --------------------------


def test_null_cache_never_hits():
    with NullCache() as c:
        c.put("k", PAYLOAD)
        assert c.get("k") is None
        assert c.entries() == 0
        assert c.stats().lookups == 0

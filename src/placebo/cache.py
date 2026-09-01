"""Persistent result cache for fault executions.

Why this exists
---------------
An audit runs the candidate suite once per fault. That is the honest way to
measure detection, and it is also why the public 33-test/185-fault audit takes
about ten minutes. Almost none of that work changes between runs: the subject
is pinned, the fault set is content-addressed, and a reviewer re-running an
audit after editing one test has invalidated exactly one column of the matrix.

So the expensive part is cached rather than made approximate. Nothing here
changes what an execution *means*; it only avoids repeating an execution whose
inputs are byte-identical to one already recorded.

Correctness rule
----------------
A cache that returns a stale answer is worse than no cache, because the whole
project's claim is that verdicts come from execution. Every input that could
change an outcome is therefore in the key, and anything not in the key is in
the environment fingerprint, which invalidates the entire cache when it moves:

    key         = subject commit, fault id, patch hash, selection
    fingerprint = interpreter, pytest, placebo, subject file digests

A miss is always safe. A hit is only produced for an exact match on both.

SQLite is used rather than a JSON file because the cache must survive
interruption: `checkpoint/resume` means a run killed halfway must not lose the
work it already did, and a transactional store gives that for free.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    key         TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS results_fingerprint ON results (fingerprint);
"""


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _package_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # pragma: no cover - absent package
        return "unknown"


def environment_fingerprint(subject_files: dict[str, str] | None = None) -> str:
    """Identity of everything outside the key that could change an outcome.

    `subject_files` maps a repository-relative path to a content digest. The
    subject's source is included because mutating a file whose baseline has
    changed produces a different program, even at the same commit, which is the
    case a dirty working tree creates.
    """
    parts = [
        f"schema={SCHEMA_VERSION}",
        f"python={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        f"pytest={_package_version('pytest')}",
        f"placebo={_package_version('placebo')}",
    ]
    for path in sorted(subject_files or {}):
        parts.append(f"{path}={subject_files[path]}")
    return _digest(*parts)


@dataclass(frozen=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0

    def to_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "hit_rate": round(self.hit_rate, 4),
        }


class ResultCache:
    """Content-addressed store of fault-execution outcomes.

    Use it as a context manager, or call `close()`. A cache whose fingerprint
    does not match the current environment behaves as empty rather than being
    silently reused.
    """

    def __init__(self, path: Path | str, fingerprint: str) -> None:
        self.path = Path(path)
        self.fingerprint = fingerprint
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Parallel workers share one cache. A connection is bound to its
        # creating thread unless told otherwise, and every access below is
        # serialised by `_lock`, so permission and safety are both explicit.
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        # Durability across an interrupted run without an fsync per write.
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.commit()
        self._hits = 0
        self._misses = 0
        self._writes = 0

    # -- identity ----------------------------------------------------------

    @staticmethod
    def key(subject_commit: str, fault_id: str, patch_hash: str,
            selection: list[str] | None = None) -> str:
        """Everything that determines the outcome of one fault execution."""
        return _digest(
            subject_commit,
            fault_id,
            patch_hash,
            "|".join(sorted(selection or [])),
        )

    @staticmethod
    def hash_patch(code: str) -> str:
        """Digest of candidate test code, normalised for line endings.

        Without normalising, the same patch checked out on Windows and Linux
        would key differently and neither would ever hit the other's entries.
        """
        normalised = code.replace("\r\n", "\n").replace("\r", "\n")
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

    # -- access ------------------------------------------------------------

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM results WHERE key = ? AND fingerprint = ?",
                (key, self.fingerprint),
            ).fetchone()
            if row is None:
                self._misses += 1
                return None
            self._hits += 1
            payload = row[0]
        return json.loads(payload)

    def put(self, key: str, payload: dict) -> None:
        """Record one result, committed before returning.

        The commit is what makes an interrupted run resumable: a fault whose
        result was known is on disk, so the next run does not re-execute it.
        """
        import time

        encoded = json.dumps(payload, sort_keys=True)
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO results "
                "(key, fingerprint, payload, created_at) VALUES (?, ?, ?, ?)",
                (key, self.fingerprint, encoded, time.time()),
            )
            self._db.commit()
            self._writes += 1

    # -- maintenance -------------------------------------------------------

    def stats(self) -> CacheStats:
        return CacheStats(hits=self._hits, misses=self._misses, writes=self._writes)

    def entries(self) -> int:
        """Entries valid for the current environment."""
        with self._lock:
            return self._db.execute(
                "SELECT COUNT(*) FROM results WHERE fingerprint = ?",
                (self.fingerprint,),
            ).fetchone()[0]

    def prune_stale(self) -> int:
        """Drop entries recorded under a different environment.

        They can never be read again, so keeping them only grows the file.
        """
        with self._lock:
            cursor = self._db.execute(
                "DELETE FROM results WHERE fingerprint != ?", (self.fingerprint,)
            )
            self._db.commit()
            return cursor.rowcount

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM results")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "ResultCache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class NullCache:
    """Disabled cache. Every lookup misses and nothing is written.

    Having an object rather than a `None` check keeps the caller's code
    identical whether caching is on or off, so the uncached path cannot drift
    away from the cached one.
    """

    fingerprint = ""

    def get(self, key: str) -> None:
        return None

    def put(self, key: str, payload: dict) -> None:
        return None

    def stats(self) -> CacheStats:
        return CacheStats()

    def entries(self) -> int:
        return 0

    def close(self) -> None:
        return None

    def __enter__(self) -> "NullCache":
        return self

    def __exit__(self, *exc) -> None:
        return None

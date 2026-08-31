# Subject provenance

This directory contains **third-party code that existed before the competition**.
It is the system under test, not part of Placebo's contribution.

| Field | Value |
|---|---|
| Project | python-semver |
| Upstream | https://github.com/python-semver/python-semver |
| Tag | `3.0.4` |
| Commit | `6adf8765f6e21910f1f0c13151ce84f32f8d431d` |
| License | BSD-3-Clause (see `LICENSE.txt`) |
| Vendored on | 2026-08-31 |

## Why this subject

- Pure Python, no compiled or network dependencies.
- Full suite: **329 tests in ~1.1 s** — fast enough to run once per mutant.
- Upstream reports **100.0% line and branch coverage**, which makes it a fair,
  non-strawman baseline for the claim that coverage does not imply fault detection.
- Dense in comparison/boundary logic, matching Placebo's operator set.

## Modifications made when vendoring

1. `tests/coerce.py` and `tests/semverwithvprefix.py` are git symlinks upstream
   (into `docs/advanced/`). Git on Windows materialises them as text files, so they
   were replaced with real copies of their targets. Content is byte-identical to
   the symlink targets at the pinned commit.
2. `__pycache__` directories removed.

No source file in `semver/` was intentionally modified. The submitted snapshot's
source hashes are pinned in `benchmark/manifests/subject_hashes.json` and checked
by `python scripts/check_consistency.py`, so any later drift is detected.

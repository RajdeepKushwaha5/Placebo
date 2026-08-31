"""Record integrity hashes for the vendored subject sources.

Why the hash is computed on normalised content
----------------------------------------------
Hashing raw bytes makes the result depend on the checkout, not on the source.
Git converts line endings on checkout, so the same commit yields CRLF on Windows
and LF on Linux. Raw-byte hashes recorded on one platform then fail on the
other, which is a false alarm about tampering rather than a real finding.

What the check is supposed to answer is "is this the same source we vendored",
so line endings are normalised to LF and a trailing newline is ignored before
hashing. A real modification still changes the digest; a checkout convention
does not.

Usage:
  python scripts/hash_subjects.py            # rewrite the manifest
  python scripts/hash_subjects.py --check    # verify without rewriting
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmark" / "manifests" / "subject_hashes.json"

SUBJECTS = {
    "subject": {
        "commit": "6adf8765f6e21910f1f0c13151ce84f32f8d431d",
        "globs": ["semver/*.py"],
    },
    "subjects/inflection": {
        "commit": "b00d4d348b32ef5823221b20ee4cbd1d2d924462",
        "globs": ["inflection/*.py"],
    },
}


def normalised_digest(path: Path) -> str:
    """sha256 of the file's content with line endings normalised to LF.

    Platform-independent, so the same vendored source produces the same digest
    on Windows and Linux.
    """
    raw = path.read_bytes()
    normalised = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").rstrip(b"\n")
    return hashlib.sha256(normalised).hexdigest()


def collect() -> dict[str, str]:
    files: dict[str, str] = {}
    for root, config in SUBJECTS.items():
        base = ROOT / root
        if not base.is_dir():
            continue
        for pattern in config["globs"]:
            for path in sorted(base.glob(pattern)):
                key = f"{root}/{path.relative_to(base).as_posix()}"
                files[key] = normalised_digest(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="verify against the manifest without rewriting it")
    args = parser.parse_args()

    current = collect()
    if not current:
        print("no subject sources found")
        return 1

    if args.check:
        if not MANIFEST.is_file():
            print("no manifest to check against")
            return 1
        stored = json.loads(MANIFEST.read_text(encoding="utf-8")).get("files", {})
        mismatched = [k for k, v in stored.items() if current.get(k) != v]
        missing = [k for k in stored if k not in current]
        extra = [k for k in current if k not in stored]
        for key in mismatched:
            print(f"  CHANGED  {key}")
        for key in missing:
            print(f"  MISSING  {key}")
        for key in extra:
            print(f"  NEW      {key}")
        problems = len(mismatched) + len(missing) + len(extra)
        print(f"  {len(stored) - problems}/{len(stored)} subject files unchanged")
        return 1 if problems else 0

    payload = {
        "algorithm": "sha256 over content with line endings normalised to LF",
        "note": "Normalised so the digest does not depend on git checkout "
                "conventions. A real source change still alters it.",
        "subjects": {root: cfg["commit"] for root, cfg in SUBJECTS.items()},
        "files": current,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"  recorded {len(current)} subject file hashes -> "
          f"{MANIFEST.relative_to(ROOT)}")
    for key in sorted(current):
        print(f"    {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fail if the committed report no longer matches the committed data.

What this is for
----------------
A report that disagrees with the artifacts behind it is worse than no report,
because it looks authoritative. This regenerates the report and compares it
against the committed copy.

Why the comparison masks some values
------------------------------------
Byte equality is the wrong test here. The report embeds wall-clock timings, and
those are properties of the machine that produced them, not claims about the
method. A GitHub runner is not the development laptop, so a strict comparison
fails on a number that was never supposed to be reproducible, while telling you
nothing about whether the findings drifted.

Masked before comparing:

* wall-clock durations ("36 s", "512 s", "1040")
* generation timestamps

Everything that constitutes a claim - counts, scores, ratios, verdicts,
fingerprints, identifiers - is compared exactly.

Usage:
  python scripts/check_report_drift.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts" / "report.md"

# Patterns whose values depend on the machine rather than on the findings.
VOLATILE = [
    (re.compile(r"\b\d+(?:\.\d+)?\s*s\b"), "<duration>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:seconds|sec)\b"), "<duration>"),
    (re.compile(r"\|\s*\d+(?:\.\d+)?\s*\|(?=\s*$)", re.MULTILINE), "| <duration> |"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:+\-]+"), "<timestamp>"),
]


def normalise(text: str) -> str:
    """Strip machine-dependent values and line-ending differences."""
    for pattern, placeholder in VOLATILE:
        text = pattern.sub(placeholder, text)
    return text.replace("\r\n", "\n").strip()


def main() -> int:
    if not REPORT.is_file():
        print("no artifacts/report.md to check")
        return 1

    committed = REPORT.read_text(encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_report.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("build_report.py failed:")
        print(result.stderr[-2000:])
        return 1

    regenerated = REPORT.read_text(encoding="utf-8")
    # Leave the working tree as it was found.
    REPORT.write_text(committed, encoding="utf-8")

    before, after = normalise(committed), normalise(regenerated)
    if before == after:
        print("  report matches the committed data (timings masked)")
        return 0

    print("  REPORT DRIFT: regenerating produced different claims\n")
    import difflib
    diff = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile="committed", tofile="regenerated", lineterm="", n=1,
    ))
    for line in diff[:40]:
        print(f"    {line}")
    if len(diff) > 40:
        print(f"    ... {len(diff) - 40} more lines")
    print("\n  Run: python scripts/build_report.py  and commit the result.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

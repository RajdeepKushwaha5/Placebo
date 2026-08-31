"""Assemble the realistic "AI added tests to your repo" artifact.

Every test here was produced by an agent during this project. Nothing is
hand-written, nothing is staged, and nothing is filtered for quality — this is
the unedited union of what the generation conditions actually emitted, which is
the situation the intended user is in: a pull request full of agent-written
tests that all look plausible.

Sources, in the order a reviewer would see them:

* `baseline_A` raw candidates   — direct-prompt output, unfiltered
* `mutant_aware_B1` / `placebo_B` / `placebo_C` / `placebo_D` — oracle-admitted
  tests authored against faults the existing suite already detects
* `real_gap_patch`              — tests authored against confirmed real gaps

Test names are prefixed by source so they can coexist; bodies are untouched.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.evaluation.repair import split_tests  # noqa: E402

HEADER = '''"""An unedited pull request of agent-written tests.

Assembled by scripts/build_as_generated_patch.py from the raw output of every
generation condition in this project. No test was hand-written, reordered by
quality, or removed. This is the input to `scripts/run_audit.py`.
"""

import pytest
import semver

'''

SUITES = [
    ("d", "placebo_D.py"),
    ("c", "placebo_C.py"),
    ("b", "placebo_B.py"),
    ("b1", "mutant_aware_B1.py"),
    ("gap", "real_gap_patch.py"),
]


def _rename(source: str, old: str, new: str) -> str:
    return re.sub(rf"\bdef\s+{re.escape(old)}\s*\(", f"def {new}(", source, count=1)


def main() -> int:
    suites_dir = ROOT / "artifacts" / "suites"
    parts = [HEADER]
    manifest: list[dict] = []

    # 1. Oracle-admitted tests from each condition.
    for tag, filename in SUITES:
        path = suites_dir / filename
        if not path.exists():
            continue
        code = path.read_text(encoding="utf-8")
        _preamble, tests = split_tests(code)
        for index, (name, source) in enumerate(tests, 1):
            new_name = f"test_ai_{tag}_{index:02d}"
            parts.append(_rename(source.strip(), name, new_name) + "\n")
            manifest.append({"test": new_name, "source_suite": filename,
                             "original_name": name})

    # 2. Raw, unfiltered direct-prompt candidates. A real PR contains these too;
    #    excluding them because they are bad would be exactly the selection bias
    #    this project exists to detect.
    raw = ROOT / "experiments" / "raw" / "pipeline_baseline_A.json"
    if raw.exists():
        payload = json.loads(raw.read_text(encoding="utf-8"))
        for index, result in enumerate(payload.get("results", []), 1):
            attempts = result.get("attempts") or []
            if not attempts:
                continue
            code = attempts[0].get("code", "")
            if not code.strip():
                continue
            try:
                tree = ast.parse(code)
            except SyntaxError:
                continue  # unparseable candidates cannot be placed in a file
            nodes = [
                n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name.startswith("test_")
            ]
            for node in nodes:
                body = ast.get_source_segment(code, node)
                if not body:
                    continue
                new_name = f"test_ai_raw_{index:02d}"
                parts.append(_rename(body.strip(), node.name, new_name) + "\n")
                manifest.append({"test": new_name, "source_suite": "baseline_A (raw)",
                                 "original_name": node.name})
                break

    out = suites_dir / "as_generated_patch.py"
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")

    manifest_path = ROOT / "artifacts" / "as_generated_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"  wrote {out.relative_to(ROOT)} with {len(manifest)} agent-written tests")
    for entry in manifest:
        print(f"    {entry['test']:20s} <- {entry['source_suite']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

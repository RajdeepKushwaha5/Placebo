"""GO/NO-GO probe: can the local model produce an ADMISSIBLE test?

Admissible means the generated test, run by the real oracle:
  1. passes on clean HEAD, and
  2. fails on the targeted mutant.

Anything else is not evidence of anything. This script proves the whole
pipeline works end to end on a single real survivor before we invest in it.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.agents.llm import LocalModel, ModelConfig  # noqa: E402
from placebo.mutation.engine import enumerate_subject  # noqa: E402
from placebo.verification.runner import SubjectRunner  # noqa: E402

SUBJECT_COMMIT = "6adf8765f6e21910f1f0c13151ce84f32f8d431d"
CANDIDATE_PATH = "tests/test_placebo_candidate.py"

SYSTEM = (
    "You are a meticulous Python test engineer. You write focused pytest tests "
    "that fail when the implementation is wrong. You output only code."
)

PROMPT = """\
The Python library `semver` has a function with a latent bug.

Here is the CURRENT (correct) source of the function under test:

```python
{source}
```

A regression has been introduced elsewhere that changes this exact line:

```diff
{diff}
```

The existing test suite does NOT catch this change. Write ONE pytest test
function that FAILS when that change is present and PASSES against the correct
code shown above.

Requirements:
- Output a complete Python file, nothing else.
- Start with `import semver`.
- Define exactly one function named `test_placebo_candidate`.
- Use plain `assert` statements on the real behavior of the function.
- Do not import pytest fixtures, do not use mocks, do not read source code.
- Pick concrete input values that make the two versions differ.

Output only the Python file inside one ```python code block.
"""


def extract_function_source(path: Path, qualname: str) -> str:
    """Return the source of `qualname` (e.g. "Version.is_compatible")."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    parts = qualname.split(".")

    def walk(nodes, remaining):
        for node in nodes:
            name = getattr(node, "name", None)
            if name != remaining[0]:
                continue
            if len(remaining) == 1:
                return ast.get_source_segment(source, node)
            return walk(getattr(node, "body", []), remaining[1:])
        return None

    return walk(tree.body, parts) or ""


def extract_code(text: str) -> str:
    """Pull the first python code block out of a model response."""
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if blocks:
        return blocks[0].strip() + "\n"
    # Some models omit fences entirely.
    if "def test_" in text:
        return textwrap.dedent(text).strip() + "\n"
    return ""


def main() -> int:
    subject = ROOT / "subject"
    census = json.loads((ROOT / "artifacts" / "census.json").read_text(encoding="utf-8"))
    mutants = {m.id: m for m in enumerate_subject(subject, ["semver/version.py"], SUBJECT_COMMIT)}
    mode = sys.argv[1] if len(sys.argv) > 1 else "survivor"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    wanted = "survived" if mode == "survivor" else "killed"
    pool = [mutants[mid] for mid, r in census.items()
            if r["status"] == wanted and mid in mutants]
    if mode == "ordinary":
        # Representative working set: one mutant per operator family, from the
        # mutants an expert human suite DOES catch. These stand in for the gaps
        # an AI-generated suite typically leaves.
        seen, picked = set(), []
        for m in pool:
            if m.operator.value not in seen:
                seen.add(m.operator.value); picked.append(m)
        pool = picked
    survivors = pool[:n]
    print(f"mode={mode}  candidates={len(survivors)}")

    if not survivors:
        print("No survivors in census; nothing to probe.")
        return 1

    model = LocalModel(
        ModelConfig(model="qwen2.5:7b"),
        trajectory=ROOT / "trajectories" / "probe.jsonl",
    )
    if not model.available():
        print(f"Model {model.config.model} not available on {model.config.host}")
        return 1
    print(f"model   : {model.config.model}  digest={model.digest()[:16]}")

    runner = SubjectRunner(subject, ROOT / ".placebo-ws" / "probe")
    runner.prepare()
    src_file = subject / "semver" / "version.py"
    full_source = src_file.read_text(encoding="utf-8")

    results = []
    for mutant in survivors:
        print(f"\n{'='*66}\nTARGET  {mutant.label}")
        func_src = extract_function_source(src_file, mutant.qualname)
        if not func_src:
            print("  could not extract function source; skipping")
            continue

        prompt = PROMPT.format(
            source=func_src[:4000], diff=mutant.diff_line(full_source)
        )
        print(f"  generating ({len(prompt)} char prompt) ...", flush=True)
        completion = model.complete(prompt, system=SYSTEM)
        if completion.error:
            print("  MODEL ERROR:", completion.error)
            continue
        print(f"  {completion.output_tokens} tok in {completion.duration_s:.0f}s "
              f"({completion.tokens_per_s:.1f} tok/s)")

        code = extract_code(completion.text)
        if not code:
            print("  no code block in response")
            results.append((mutant.id, "NO_CODE"))
            continue
        print("  --- generated test ---")
        print(textwrap.indent(code.strip()[:600], "  | "))

        # Gate 1: passes on clean HEAD
        with runner.extra_tests({CANDIDATE_PATH: code}):
            clean = runner.run_suite([CANDIDATE_PATH])
        if not clean.passed:
            print(f"  REJECTED: fails on clean HEAD (rc={clean.returncode})")
            results.append((mutant.id, "CLEAN_HEAD_FAILED"))
            continue

        # Gate 2: fails on the targeted mutant
        run = runner.run_mutant(mutant, selection=[CANDIDATE_PATH], extra={CANDIDATE_PATH: code})
        if run.status.value == "killed":
            print("  ADMITTED: passes clean, fails on mutant  <-- this is the oracle working")
            results.append((mutant.id, "ADMITTED"))
        else:
            print(f"  REJECTED: mutant survived the candidate ({run.status.value})")
            results.append((mutant.id, "TARGET_MUTANT_SURVIVED"))

    print(f"\n{'='*66}\nPROBE RESULT")
    for mid, verdict in results:
        print(f"  {mid}  {verdict}")
    admitted = sum(1 for _, v in results if v == "ADMITTED")
    print(f"\n  admitted {admitted}/{len(results)}")
    print(f"  usage: {model.usage()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

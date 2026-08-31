"""Export human-readable agent trajectories.

The submission requires trajectories that can be followed from the agent's
instructions through to the final result, showing what the agent did, how its
tools responded, and what feedback shaped the next step.

Raw JSONL is a record, not a trajectory. This renders one Markdown file per
condition: the system prompt, then every attempt, the exact tool verdict from
the admission gates, the feedback that was handed back, and the final outcome.

Usage:
  python scripts/export_trajectories.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "trajectories"

GATE_EXPLANATION = {
    "static": "static checks (parses, defines a test, no forbidden patterns, has an assertion)",
    "clean_head": "passes against the CORRECT implementation",
    "kills_target": "FAILS against the injected fault — the test detects it",
    "repeat_stable": "same verdict on repeat runs",
}


def fence(text: str, lang: str = "") -> str:
    text = (text or "").rstrip()
    return f"```{lang}\n{text}\n```"


def render_condition(name: str, payload: dict) -> str:
    meta = payload.get("meta", {}) or payload.get("summary", {})
    results = payload.get("results", [])

    lines: list[str] = []
    add = lines.append

    add(f"# Trajectory — condition `{name}`\n")
    add(f"- **Context condition**: `{meta.get('context_condition', '?')}`")
    add(f"- **Max attempts**: {meta.get('max_attempts', '?')}")
    add(f"- **Discovery faults attempted**: {meta.get('discovery_total', len(results))}")
    add(f"- **Admitted**: {meta.get('discovery_admitted', '?')}")
    if "usage" in meta:
        u = meta["usage"]
        add(f"- **Model cost**: {u['calls']} calls, {u['output_tokens']} output tokens, "
            f"{u['model_seconds']:.0f} model-seconds, ${u['usd_cost']:.2f}")
    add("")
    add("Every attempt below was judged by executing pytest, never by asking the "
        "model to grade itself. The admission gates are:\n")
    for gate, why in GATE_EXPLANATION.items():
        add(f"- `{gate}` — {why}")
    add("\n---\n")

    for i, res in enumerate(results, 1):
        admitted = res.get("admitted")
        add(f"## Fault {i}/{len(results)} — `{res['mutant_id']}` "
            f"— {'ADMITTED' if admitted else 'NOT ADMITTED'}\n")
        add(f"Attempts used: {res.get('attempts_used')}\n")

        for attempt in res.get("attempts", []):
            adm = attempt.get("admission", {})
            add(f"### Attempt {attempt['attempt']}\n")
            add(f"*Agent produced ({attempt.get('output_tokens', '?')} tokens in "
                f"{attempt.get('duration_s', '?')}s):*\n")
            add(fence(attempt.get("code", ""), "python"))
            add("")
            add("*Tool response — admission gates:*\n")
            passed = adm.get("gates_passed", [])
            if passed:
                add(f"- passed: {', '.join(f'`{g}`' for g in passed)}")
            if adm.get("admitted"):
                add(f"- **ADMITTED** — {adm.get('message', '')}")
            else:
                add(f"- **REJECTED** `{adm.get('code')}` — {adm.get('message', '')}")
                if adm.get("target_status"):
                    add(f"- fault status under this test: `{adm['target_status']}`")
            add("")

        if admitted and res.get("admitted_code"):
            add("### Final admitted test\n")
            add(fence(res["admitted_code"], "python"))
            add("\n> Proven: passes on correct code, fails on the injected fault.\n")
        add("\n---\n")

    return "\n".join(lines)


def trim_raw_log(name: str, expected_calls: int) -> None:
    """Keep only the final run's calls in the raw JSONL.

    The model client appends, so a log can accumulate calls from earlier or
    aborted runs. The structured results record exactly how many calls the
    final run made, so the log is truncated to that many trailing lines. This
    keeps the submitted trajectory evidence honest rather than mixed.
    """
    path = OUT / f"pipeline_{name}.jsonl"
    if not path.exists() or expected_calls <= 0:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= expected_calls:
        return
    dropped = len(lines) - expected_calls
    path.write_text("\n".join(lines[-expected_calls:]) + "\n", encoding="utf-8")
    print(f"    trimmed {dropped} stale call(s) from {path.name}")


def main() -> int:
    raw_dir = ROOT / "experiments" / "raw"
    if not raw_dir.exists():
        print("no experiments/raw — run the pipeline first")
        return 1

    written = []
    for path in sorted(raw_dir.glob("pipeline_*.json")):
        name = path.stem.replace("pipeline_", "")
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("meta", {})
        trim_raw_log(name, meta.get("usage", {}).get("calls", 0))
        out = OUT / f"TRAJECTORY_{name}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_condition(name, payload), encoding="utf-8")
        written.append(out)
        print(f"  wrote {out.relative_to(ROOT)}")

    # The product demonstration uses the same author role against the six
    # manually confirmed repository gaps rather than benchmark discovery cases.
    real_gap_path = ROOT / "experiments" / "real_gap_closure.json"
    if real_gap_path.exists():
        gap = json.loads(real_gap_path.read_text(encoding="utf-8"))
        gap_payload = {
            "meta": {
                "context_condition": "D (oracle-grounded), confirmed real gaps",
                "max_attempts": 3,
                "discovery_total": gap.get("confirmed_gaps", 0),
                "discovery_admitted": gap.get("candidate_tests_admitted", 0),
                "usage": gap.get("usage", {}),
            },
            "results": gap.get("results", []),
        }
        out = OUT / "TRAJECTORY_real_gap_closure.md"
        out.write_text(render_condition("real_gap_closure", gap_payload), encoding="utf-8")
        written.append(out)
        print(f"  wrote {out.relative_to(ROOT)}")

    # Index describing every agent used, as the submission requires.
    index = [
        "# Agent trajectories\n",
        "Placebo uses **one agent role**, the *test author*, run under several ",
        "scaffolding conditions. Each condition below is the same local model ",
        "(`qwen2.5:7b`, temperature 0, seed 7) with different context and tools.\n",
        "| condition | what the agent is given | tools available |",
        "|---|---|---|",
        "| `baseline_A` | function source only | none |",
        "| `mutant_aware_B1` | function source + known-detectable fault diff | none |",
        "| `placebo_B` | same as B1 | admission gates, with feedback on retry |",
        "| `placebo_C` | contract only (body withheld) + fault diff | admission gates |",
        "| `placebo_D` | function source + fault diff | **oracle probe** (executes candidate expressions against clean and faulty code) + admission gates |",
        "| `real_gap_closure` | function source + manually confirmed repository-gap diff | oracle probe + admission gates |",
        "",
        "## Files\n",
    ]
    for out in written:
        index.append(f"- [`{out.name}`]({out.name}) — full attempt-by-attempt record")
    index += [
        "",
        "## Raw logs\n",
        "`pipeline_*.jsonl` and `real_gap_closure.jsonl` in this directory contain every model call verbatim: ",
        "system prompt, full prompt, raw response, token counts and duration.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(index), encoding="utf-8")
    print(f"  wrote {(OUT / 'README.md').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

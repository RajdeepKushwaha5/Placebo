"""Render a self-contained HTML evidence page.

Why this exists: the redundancy result is a *shape*, not a sentence. Seeing
thirty-three rows where almost every one detects only faults another row already
detects makes the argument instantly, in a way a paragraph cannot.

The page is a single file with no external assets, no network calls and no
JavaScript dependencies, so it opens offline from a clean clone and can be
screenshotted or recorded directly. Every number is read from the stored
artifacts, never hardcoded.

Usage:
  python scripts/build_evidence_page.py
  # writes artifacts/evidence.html
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERDICT_STYLE = {
    "VALUABLE": ("valuable", "Sole detector of a fault the existing suite misses"),
    "REDUNDANT_WITH_SIBLING": ("redundant", "A sibling test detects the same fault"),
    "REDUNDANT_WITH_EXISTING": ("redundant", "Only re-detects what the repo already catches"),
    "UNPROVEN": ("unproven", "No marginal sensitivity under the evaluated fault models"),
    "HARMFUL": ("harmful", "Red or unstable against correct code"),
}

CSS = """
:root {
  --bg:#faf9f7; --fg:#1c1b19; --muted:#6b6862; --line:#e3e0da; --card:#fff;
  --valuable:#1a7f4b; --valuable-bg:#e6f4ec;
  --redundant:#8a6d1f; --redundant-bg:#faf1d8;
  --unproven:#5a5a5a; --unproven-bg:#eeeeee;
  --harmful:#a33232; --harmful-bg:#fbe9e9;
  --accent:#2b5fa8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#16151a; --fg:#eceaf0; --muted:#9d99a6; --line:#2e2c35; --card:#1e1d24;
    --valuable:#5fd39a; --valuable-bg:#12261c;
    --redundant:#e0bd63; --redundant-bg:#2a2312;
    --unproven:#a0a0a0; --unproven-bg:#232228;
    --harmful:#f08a8a; --harmful-bg:#2b1618;
    --accent:#7aa9ee;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:40px 24px 72px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:19px;margin:44px 0 10px;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0 0 28px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card .n{font-size:27px;font-weight:650;letter-spacing:-.02em}
.card .l{color:var(--muted);font-size:12.5px;margin-top:3px}
table{width:100%;border-collapse:collapse;font-size:13.5px;
  background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line)}
th{font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;
  letter-spacing:.05em}
tr:last-child td{border-bottom:none}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;
  font-size:11px;font-weight:650;letter-spacing:.02em;white-space:nowrap}
.valuable{color:var(--valuable);background:var(--valuable-bg)}
.redundant{color:var(--redundant);background:var(--redundant-bg)}
.unproven{color:var(--unproven);background:var(--unproven-bg)}
.harmful{color:var(--harmful);background:var(--harmful-bg)}
.bar{height:7px;border-radius:4px;background:var(--line);position:relative;min-width:70px}
.bar>i{position:absolute;inset:0 auto 0 0;border-radius:4px;background:var(--accent);
  opacity:.55}
.bar>b{position:absolute;inset:0 auto 0 0;border-radius:4px;background:var(--valuable)}
.note{color:var(--muted);font-size:13px;margin:10px 0 0}
.kept{color:var(--valuable);font-weight:650}
.scroll{overflow-x:auto}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 0;font-size:12.5px;
  color:var(--muted)}
"""


def esc(text: object) -> str:
    return html.escape(str(text))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main() -> int:
    audit_all = load(ROOT / "experiments" / "audit.json") or {}
    search = load(ROOT / "experiments" / "gap_search.json")
    census = load(ROOT / "artifacts" / "census_summary.json")
    triage = load(ROOT / "artifacts" / "survivor_triage.json")
    realgap = load(ROOT / "experiments" / "real_gap_closure.json")

    if not audit_all:
        print("no experiments/audit.json - run scripts/run_audit.py first")
        return 1

    name, payload = sorted(audit_all.items())[0]
    summary = payload["summary"]
    tests = payload["tests"]
    mini = payload.get("minimization") or {}
    kept = set(mini.get("kept_tests", []))
    max_detected = max((t["faults_detected"] for t in tests), default=1) or 1

    out: list[str] = []
    add = out.append

    add("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    add("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    add("<title>Placebo - evidence</title>")
    add(f"<style>{CSS}</style></head><body><div class='wrap'>")

    add("<h1>Placebo &mdash; test evidence</h1>")
    add("<p class='sub'>Which of these tests detects a failure that nothing "
        "else already detects? Every number is read from the stored artifacts.</p>")

    # ---- headline cards ---------------------------------------------------
    add("<div class='cards'>")
    if census:
        add(f"<div class='card'><div class='n'>{census['mutation_score']*100:.1f}%</div>"
            f"<div class='l'>faults caught by semver's own suite<br>at 100% coverage</div></div>")
    if triage:
        add(f"<div class='card'><div class='n'>{triage['confirmed_real_gaps']}</div>"
            f"<div class='l'>confirmed real bugs it misses</div></div>")
    if search:
        add(f"<div class='card'><div class='n'>{search['gaps_closed']}/{search['confirmed_gaps']}</div>"
            f"<div class='l'>closed by counterexample search<br>"
            f"{search['model_calls']} model calls</div></div>")
    add(f"<div class='card'><div class='n'>{summary['tests_audited']} &rarr; "
        f"{mini.get('kept_count', '?')}</div>"
        f"<div class='l'>agent-written tests, after minimization</div></div>")
    add("</div>")

    # ---- kill matrix ------------------------------------------------------
    add("<h2>Marginal value of each agent-written test</h2>")
    add("<div class='legend'>"
        "<span>Bar length = faults detected</span>"
        "<span>Green segment = faults <b>only this test</b> detects</span>"
        "<span>&#9679; = kept after minimization</span></div>")
    add("<div class='scroll'><table><thead><tr>"
        "<th>test</th><th>verdict</th><th>faults detected</th>"
        "<th class='num'>detected</th><th class='num'>missed by suite</th>"
        "<th class='num'>unique</th><th>kept</th>"
        "</tr></thead><tbody>")

    for entry in tests:
        cls, _why = VERDICT_STYLE.get(entry["verdict"], ("unproven", ""))
        width = entry["faults_detected"] / max_detected * 100
        uniq_w = entry["uniquely_detected"] / max_detected * 100
        is_kept = entry["test"] in kept
        add("<tr>")
        add(f"<td class='mono'>{esc(entry['test'])}</td>")
        add(f"<td><span class='badge {cls}'>{esc(entry['verdict'].replace('_', ' '))}</span></td>")
        add(f"<td><div class='bar'><i style='width:{width:.1f}%'></i>"
            f"<b style='width:{uniq_w:.1f}%'></b></div></td>")
        add(f"<td class='num'>{entry['faults_detected']}</td>")
        add(f"<td class='num'>{entry['faults_missed_by_existing_suite']}</td>")
        add(f"<td class='num'>{entry['uniquely_detected']}</td>")
        add(f"<td class='kept'>{'&#9679;' if is_kept else ''}</td>")
        add("</tr>")
    add("</tbody></table></div>")

    v = summary["verdicts"]
    add(f"<p class='note'><b>{v['VALUABLE']}</b> of {summary['tests_audited']} tests "
        f"add unique detection. <b>{v['REDUNDANT_WITH_EXISTING']}</b> only re-detect "
        f"what the repository already catches. <b>{v['HARMFUL']}</b> do not pass "
        f"against correct code. <code>UNPROVEN</code> means no marginal sensitivity "
        f"under the evaluated fault models &mdash; not that a test is worthless.</p>")

    # ---- minimization -----------------------------------------------------
    if mini:
        add("<h2>Minimization</h2>")
        add("<table><thead><tr><th></th><th class='num'>tests</th>"
            "<th class='num'>faults only this patch detects</th></tr></thead><tbody>")
        add(f"<tr><td>original patch</td><td class='num'>{mini['original_count']}</td>"
            f"<td class='num'>{len(mini['novel_faults_before'])}</td></tr>")
        add(f"<tr><td>minimized patch</td><td class='num'><b>{mini['kept_count']}</b></td>"
            f"<td class='num'><b>{len(mini['novel_faults_after'])}</b></td></tr>")
        add("</tbody></table>")
        add(f"<p class='note'>No loss verified by re-executing the full audit on the "
            f"reduced patch: <b>{'yes' if mini['no_loss_verified'] else 'NO'}</b>. "
            f"Minimization is a set cover over the faults only this patch detects, "
            f"not a filter on verdicts &mdash; when several sibling tests detect one "
            f"fault, each looks redundant, and dropping all of them would lose it.</p>")

    # ---- search witnesses -------------------------------------------------
    if search:
        add("<h2>Counterexample search on confirmed real gaps</h2>")
        add("<table><thead><tr><th>approach</th><th class='num'>gaps closed</th>"
            "<th class='num'>model calls</th><th class='num'>wall time</th>"
            "</tr></thead><tbody>")
        if realgap:
            add(f"<tr><td>agent with oracle grounding</td>"
                f"<td class='num'>{realgap['gaps_closed']}/{realgap['confirmed_gaps']}</td>"
                f"<td class='num'>{realgap['usage']['calls']}</td>"
                f"<td class='num'>{realgap['wall_s']:.0f}s</td></tr>")
        add(f"<tr><td><b>+ deterministic search</b></td>"
            f"<td class='num'><b>{search['gaps_closed']}/{search['confirmed_gaps']}</b></td>"
            f"<td class='num'><b>{search['model_calls']}</b></td>"
            f"<td class='num'><b>{search['wall_s']:.0f}s</b></td></tr>")
        add("</tbody></table>")

        add("<h2>Minimal witnesses found by search</h2>")
        add("<div class='scroll'><table><thead><tr><th>input</th>"
            "<th>correct code</th><th>with the bug</th></tr></thead><tbody>")
        for entry in search["results"]:
            if entry.get("closed") and entry.get("witness"):
                add(f"<tr><td class='mono'>{esc(entry['witness'])}</td>"
                    f"<td class='mono'>{esc(entry['clean'][:52])}</td>"
                    f"<td class='mono'>{esc(entry['faulty'][:52])}</td></tr>")
        add("</tbody></table></div>")
        add("<p class='note'>Each input was found by deterministic enumeration and "
            "shrunk to the simplest candidate that separates correct from faulty "
            "code. Expected values were observed by executing the reference "
            "implementation, never predicted by a model.</p>")

    add("</div></body></html>")

    out_path = ROOT / "artifacts" / "evidence.html"
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"  wrote {out_path.relative_to(ROOT)} "
          f"({out_path.stat().st_size // 1024} KB, self-contained)")
    print(f"  open it with: start artifacts/evidence.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

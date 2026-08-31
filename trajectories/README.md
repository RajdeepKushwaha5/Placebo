# Agent trajectories

Placebo uses **one agent role**, the *test author*, run under several 
scaffolding conditions. Each condition below is the same local model 
(`qwen2.5:7b`, temperature 0, seed 7) with different context and tools.

| condition | what the agent is given | tools available |
|---|---|---|
| `baseline_A` | function source only | none |
| `mutant_aware_B1` | function source + known-detectable fault diff | none |
| `placebo_B` | same as B1 | admission gates, with feedback on retry |
| `placebo_C` | contract only (body withheld) + fault diff | admission gates |
| `placebo_D` | function source + fault diff | **oracle probe** (executes candidate expressions against clean and faulty code) + admission gates |
| `real_gap_closure` | function source + manually confirmed repository-gap diff | oracle probe + admission gates |

## Files

- [`TRAJECTORY_baseline_A.md`](TRAJECTORY_baseline_A.md) — full attempt-by-attempt record
- [`TRAJECTORY_mutant_aware_B1.md`](TRAJECTORY_mutant_aware_B1.md) — full attempt-by-attempt record
- [`TRAJECTORY_placebo_B.md`](TRAJECTORY_placebo_B.md) — full attempt-by-attempt record
- [`TRAJECTORY_placebo_C.md`](TRAJECTORY_placebo_C.md) — full attempt-by-attempt record
- [`TRAJECTORY_placebo_D.md`](TRAJECTORY_placebo_D.md) — full attempt-by-attempt record
- [`TRAJECTORY_real_gap_closure.md`](TRAJECTORY_real_gap_closure.md) — full attempt-by-attempt record

## Raw logs

`pipeline_*.jsonl` and `real_gap_closure.jsonl` in this directory contain every model call verbatim: 
system prompt, full prompt, raw response, token counts and duration.

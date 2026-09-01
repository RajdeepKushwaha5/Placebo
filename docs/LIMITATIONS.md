# Limitations

Written to be read by someone trying to find the weak points, because that is a
better use of a reviewer's time than a list of strengths.

**Start with section 9** if you only read one: the expected values in every
generated test are a snapshot of current behavior, not verified correctness.
**Section 10** reports the equal-compute baseline control.

## 1. Mutation score is a proxy, not ground truth

Placebo measures detection of **injected single-token faults**, not detection of
real bugs. The literature is genuinely split on how well the two correlate: one
study finds a coverage-independent relationship, another finds the correlation
weak once suite size and mutation location are controlled for.

Concretely, what this means here:

- Single-token mutants are not distributed like real defects. Real bugs are
  often missing cases, wrong abstractions, or interactions between functions.
  This operator set produces none of those.
- A suite optimized against a fixed operator set could in principle overfit to
  that set. Placebo's held-out split limits this (the agent never sees the
  scored faults) but does not remove it, because held-out faults are drawn from
  the same seven operator families.

**Partly addressed since.** `scripts/run_historical_bugs.py` evaluates four
defects that genuinely shipped in semver 3.0.4 and were fixed upstream
afterwards, using the maintainers' own diffs and issue numbers as ground truth.
Deterministic search found a distinguishing witness for **3 of the 3
behavior-changing bugs**, and correctly found none for the one
behavior-preserving refactor. That is four real bugs, not four hundred: it
removes the "only synthetic faults" objection for a small sample without
substituting for a BugsInPy-scale study, which remains the right next step.

## 2. Equivalent mutants

Some mutants cannot be killed by any test because they do not change behavior.
Counting them as survivors understates a suite's true score.

All 7 survivors of semver's own suite were triaged by hand
(`scripts/triage_survivors.py`, results in `artifacts/survivor_triage.json`):

- **6 confirmed real gaps**: a killing test was written and verified for each.
- **1 confirmed equivalent**: the mutant sits in genuinely dead code:
  `bump_build` in semver 3.0.4 computes `build`, increments it, then recomputes
  the identical `if/elif` chain and increments again, discarding the first
  result entirely.

So the reported **96.2%** is a lower bound and the equivalence-adjusted figure
is **96.7%**. The held-out sets used for scoring exclude this problem by
construction: they contain only mutants that semver's own suite demonstrably
kills, so every scored fault is known to be detectable.

## 3. Sample size and effect size

The primary held-out set is 80 faults across 12 functions of one module of one
library. Differences between conditions are a handful of mutants. Treat the
ordering of the middle conditions as indicative, not established.

No significance testing is claimed for the between-condition comparison.
Run-to-run variance *is* now measured, from three stored independent runs of the
same condition (`experiments/variance.json`): admitted counts were identical in
all three (95% bootstrap CI [5.0, 5.0]) while retry recoveries ranged 0-2 (CI
[0.0, 2.0]). Three runs give a very wide interval; it is reported rather than
smoothed. Per-condition, per-fault results are in `experiments/results.json` so
anyone can compute their own statistics.

## 4. Nondeterminism in generation

Ollama with partial GPU offload is **not bitwise deterministic**, even at
`temperature=0` with a fixed seed. Two runs of an identical first-attempt prompt
produced different outputs during development.

- **Deterministic:** the fault inventory, mutant ids, the census, both split
  fingerprints, and every admission verdict (those are pytest runs).
- **Not deterministic:** model outputs, and therefore per-condition scores.

The headline table in the README reports **single runs**. Three conditions have
since been repeated three times each:

| condition | runs | measure | median | range | source |
|---|---:|---|---:|---|---|
| `baseline_A` | 3 | faults admitted of 12 | 0 | 0-1 | `experiments/seeds.json` |
| `placebo_D` | 3 | faults admitted of 12 | 7 | 6-7 | `experiments/seeds.json` |
| `placebo_B` | 3 | tests kept | 5 | 5-5 | `experiments/variance.json` |

The two extremes were repeated on the same 12-fault subset, so they are directly
comparable, and their ranges do not overlap: the *worst* `placebo_D` run still
admitted six times what the *best* `baseline_A` run did. That rules out a single
lucky run as the explanation for the gap between them. It does not make the
comparison precise. Three runs over twelve faults is a small sample, the
bootstrap intervals are correspondingly wide, and the subset is not the 29-fault
confirmatory split the headline percentages are computed on.

`mutant_aware_B1` and `placebo_C` remain single runs. Nothing here establishes
the ordering *between* the middle conditions, only that the two ends are
separated by more than run-to-run noise.

## 5. One subject, one language

Everything here is Python and pytest. There are now **two** subjects, not one:
`semver` (comparison and boundary logic, 329 tests) and `inflection` (string
transformation, 455 tests). Their mutation scores differ substantially, which is
the useful part: the method reports a property of each suite rather than a
constant. Two Python libraries is still a narrow base. Nothing here establishes
that the result transfers to other languages, larger modules, or codebases with
slow test suites.

Placebo's mutation engine also assumes a fast suite: it runs the tests once per
fault. On a subject with a ten-minute suite, the census alone would take days.

## 6. The agent is small

`qwen2.5:7b` at Q4_K_M on a 4 GB GPU. A stronger model would very likely raise
every condition's absolute numbers.

This cuts both ways and should be read carefully. The **comparison** is
paired (every condition uses the same model, seed and gates), so the *relative*
finding is meaningful. Retry recoveries varied from zero to two cases across
three stored runs with nominally fixed settings, so no strong claim about retry
effectiveness is justified. A stronger model may use corrective feedback more
consistently; the robust finding here is narrower: removing expected-value
prediction eliminated `CLEAN_HEAD_FAILED` by construction.

## 7. What Placebo does not do

- It does not prove correctness, and cannot.
- It does not find unknown real bugs. It closes measured gaps against faults it
  injected itself.
- It does not judge whether a test is *well written*, only whether it detects
  something.
- It does not merge anything. Output is a proposal for a qualified human
  reviewer, and the evidence bundle exists so that review is cheap.

## 8. Known rough edges

- The green-test repair runs each test in a separate pytest process, which is
  correct but slow on large suites.
- Coverage is measured for the generated suite alone, not for the union with the
  existing suite; the union is what a real repository would have.
- The oracle probe executes a deliberately small AST-validated expression DSL
  in a subprocess with Python builtins disabled. It rejects non-`semver` names,
  dunder access, direct function calls, comprehensions and control-flow
  expressions.
- Execution now happens inside a networkless container with a read-only root, a
  read-only subject mount, dropped capabilities, a non-root user and capped cpu,
  memory, processes and time. Eleven adversarial tests start real containers and
  attempt the escape rather than assuming it is blocked. This is a strong
  boundary and not a perfect one: a kernel escape is outside what it addresses,
  and a subject whose own suite deletes its working directory will succeed in
  deleting the copy. Running without it requires `--unsafe-local`, and which one
  ran is recorded in the evidence bundle. See `SANDBOX.md`.
- Execution happens in a disposable directory copy, one per run, under
  `.placebo-ws/<repository>/<commit>/<run-id>/`. Concurrent runs against the
  same repository were previously a real hazard, since they shared a directory
  and one would delete the other's subject files mid-audit; that is fixed and
  covered by `tests/test_workspace_isolation.py`, which asserts that neither
  run's workspace is destroyed, neither run's results are contaminated, both
  caches stay valid, and cleanup removes only the owning run. Directories left
  by a crashed run are swept after a day.

## 9. The oracle problem: what an "expected value" actually means

This is the sharpest limitation in the project and the one most likely to matter
in real use.

Oracle grounding (condition D) works like this:

```
run the chosen input against the reference implementation
        -> use whatever it returned as the expected value
```

That guarantees **consistency with the current implementation**, not
**correctness with respect to intent**. If `semver` already contained a bug on
some input, Placebo would faithfully record the buggy output as expected, and
the resulting test would lock that bug in. That is the same
implementation-copying failure this project criticizes in AI-written tests,
displaced one level.

What the witness therefore pins is behavior against *change*, not against
*error*. That is genuinely useful for regression detection and genuinely
insufficient for correctness.

### The oracle hierarchy this should use

| level | oracle | strength | used here |
|---|---|---|:--:|
| 1 | explicit specification, examples, invariants | correctness w.r.t. intent | no |
| 2 | agreement between independent implementations | correctness by cross-check | no |
| 3 | metamorphic properties (`parse(str(v)) == v`, `compare(a,b) == -compare(b,a)`) | correctness of relationships, no hardcoded outputs | **yes** |
| 4 | single-reference execution snapshot | consistency only | **yes** |

Placebo's default oracle is **level 4** and is labelled as such rather than
presented as ground truth. **Level 3 is now implemented**
(`src/placebo/search/metamorphic.py`): twelve properties, all verified to hold
on clean code, asserting relationships rather than recorded outputs.

The measured trade-off is worth stating plainly, because it went against
expectation: the *stronger* oracle is the *weaker* detector. Snapshot witnesses
close **6/6** confirmed gaps but pin behavior rather than correctness;
metamorphic properties close **1/6** but cannot encode an existing bug as
expected. Neither dominates, and Placebo reports both rather than picking the
flattering one. Level 2 (independent implementations) remains unimplemented, and
no result in this project should be read as a correctness claim.

### Why the measured results still stand

The comparison between conditions is unaffected: every condition is scored
against the same injected faults with the same oracle, so the *relative* finding
holds. What the snapshot oracle limits is the absolute interpretation: "this
test detects a regression" is supported; "this test verifies the function is
right" is not.

## 10. Compute budget, now controlled for

Placebo's best condition uses more model calls than the direct-prompt baseline,
so a fair objection follows: did the scaffolding help, or did it simply buy more
attempts? Recent work suggests plain resampling at equal budget can rival
feedback-driven loops, so this needed a measurement rather than an argument.

**Status: run.** `scripts/run_equal_budget.py` gave the plain prompt three
independent draws per fault and scored the result two ways, as a developer would
use it (keep the first candidate green on correct code) and under a generous
best-of-N reading (did any draw detect the fault).

| approach | model calls | faults detected |
|---|---:|---:|
| direct prompt, 3 independent draws | 36 | 3/12 |
| oracle-grounded scaffolding | 23 | 7/12 |

The resampled baseline spent **more** compute and detected **fewer** faults, on
the same twelve faults with the same model and the same admission gates. Extra
attempts are not the mechanism.

This closes the objection for this subject and this model. It does not
generalise on its own: one subject, one model, one run of each arm.


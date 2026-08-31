# Limitations

Written to be read by someone trying to find the weak points, because that is a
better use of a reviewer's time than a list of strengths.

**Start with section 9** if you only read one: the expected values in every
generated test are a snapshot of current behavior, not verified correctness.
**Section 10** names the one control that is implemented but not yet run.

## 1. Mutation score is a proxy, not ground truth

Placebo measures detection of **injected single-token faults**, not detection of
real bugs. The literature is genuinely split on how well the two correlate: one
study finds a coverage-independent relationship, another finds the correlation
weak once suite size and mutation location are controlled for.

Concretely, what this means here:

- Single-token mutants are not distributed like real defects. Real bugs are
  often missing cases, wrong abstractions, or interactions between functions —
  none of which this operator set produces.
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

- **6 confirmed real gaps** — a killing test was written and verified for each.
- **1 confirmed equivalent** — the mutant sits in genuinely dead code:
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

Reported condition numbers are **single runs**. Repeating with several seeds and
reporting medians is the obvious next step and was not done for time.

## 5. One subject, one language

Everything here is Python and pytest. There are now **two** subjects, not one:
`semver` (comparison and boundary logic, 329 tests) and `inflection` (string
transformation, 455 tests). Their mutation scores differ substantially, which is
the useful part — the method reports a property of each suite rather than a
constant. Two Python libraries is still a narrow base. Nothing here establishes
that the result transfers to other languages, larger modules, or codebases with
slow test suites.

Placebo's mutation engine also assumes a fast suite: it runs the tests once per
fault. On a subject with a ten-minute suite, the census alone would take days.

## 6. The agent is small

`qwen2.5:7b` at Q4_K_M on a 4 GB GPU. A stronger model would very likely raise
every condition's absolute numbers.

This cuts both ways and should be read carefully. The **comparison** is
paired — every condition uses the same model, seed and gates — so the *relative*
finding is meaningful. Retry recoveries varied from zero to two cases across
three stored runs with nominally fixed settings, so no strong claim about retry
effectiveness is justified. A stronger model may use corrective feedback more
consistently; the robust finding here is narrower: removing expected-value
prediction eliminated `CLEAN_HEAD_FAILED` by construction.

## 7. What Placebo does not do

- It does not prove correctness, and cannot.
- It does not find unknown real bugs — it closes measured gaps against faults it
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
  expressions. The workspace is disposable, but this is still not a hardened
  OS/container boundary; production use against untrusted model providers
  should add a networkless container and resource limits.

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
the resulting test would lock that bug in — the same implementation-copying
failure this project criticizes in AI-written tests, displaced one level.

What the witness therefore pins is behavior against *change*, not against
*error*. That is genuinely useful for regression detection and genuinely
insufficient for correctness.

### The oracle hierarchy this should use

| level | oracle | strength | used here |
|---|---|---|:--:|
| 1 | explicit specification, examples, invariants | correctness w.r.t. intent | no |
| 2 | agreement between independent implementations | correctness by cross-check | no |
| 3 | metamorphic properties (`parse(str(v)) == v`, `compare(a,b) == -compare(b,a)`) | correctness of relationships, no hardcoded outputs | no |
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
holds. What the snapshot oracle limits is the absolute interpretation — "this
test detects a regression" is supported; "this test verifies the function is
right" is not.

## 10. Compute budget is not controlled for

Placebo's best condition uses more model calls than the direct-prompt baseline
(23 versus 12 on the same twelve faults). A fair objection follows: did the
scaffolding help, or did it simply buy more attempts? Recent work suggests plain
resampling at equal budget can rival feedback-driven loops, so this deserves a
measurement rather than an argument.

**Status: implemented, not run.** `scripts/run_equal_budget.py` draws N
independent samples from the *plain* prompt at matched budget and scores them
two ways — what a developer would keep (the first candidate green on clean code)
and the generous best-of-N reading (did *any* draw detect the fault). It is a
single command:

```bash
python scripts/run_equal_budget.py --samples 3 --limit 12
```

It did not run before submission because the local model server was stopped for
memory reasons and a ~25-minute generation run did not fit the remaining window.
No result from it is claimed anywhere.

What can be said from data already collected: the `mutant_aware_B1` versus
`placebo_B` pair *is* a budget comparison at fixed context — one attempt versus
three, 12 calls versus 29 — and the extra attempts bought 3/12 to 5/12. The
largest gain in the project came from the opposite direction: deterministic
counterexample search closed 6/6 with **zero** model calls. That is suggestive
that budget was not the mechanism, but it is not the controlled experiment, and
this section stays open until that command has been run.

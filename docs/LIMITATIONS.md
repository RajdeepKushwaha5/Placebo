# Limitations

Written to be read by someone trying to find the weak points, because that is a
better use of a reviewer's time than a list of strengths.

**Start with section 9** if you only read one: the expected values in every
generated test are a snapshot of current behavior, not verified correctness.

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

**Not done, and it should be:** validating the final suites against a corpus of
real historical bugs (BugsInPy or similar). That was scoped out for time and is
the single most valuable next experiment.

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

No significance testing is claimed. Per-condition, per-fault results are in
`experiments/results.json` so anyone can compute their own statistics.

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

Everything here is Python, pytest, and one module of one library. The subject
was chosen because it is real, permissively licensed, fast to run, and held to
100% coverage — which makes it a fair rather than flattering target. It is still
one data point. Nothing here establishes that the result transfers to other
languages, larger modules, or codebases with slow test suites.

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

Placebo operates at **level 4** and labels it as such rather than presenting a
snapshot as ground truth. Levels 2 and 3 are the highest-value next work:
semver has natural metamorphic properties, and a previous stable release would
serve as an independent second reference. Neither was implemented, and no result
in this project should be read as a correctness claim.

### Why the measured results still stand

The comparison between conditions is unaffected: every condition is scored
against the same injected faults with the same oracle, so the *relative* finding
holds. What the snapshot oracle limits is the absolute interpretation — "this
test detects a regression" is supported; "this test verifies the function is
right" is not.

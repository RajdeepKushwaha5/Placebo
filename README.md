# Placebo

> Your test suite got bigger. Did its ability to catch faults get better?

Placebo audits a test suite for fault classes it does not detect, then produces
**evidence-carrying test patches** — tests admitted only after execution shows they
pass against clean code and fail against a specific injected fault. Improvement
claims are scored on **faults the generation agent never saw**. A 29-fault
stratified set was frozen before generation; an all-eligible 80-fault set is
also reported under a deterministic, no-sampling rule.

It runs entirely on a **local model** on a consumer laptop GPU. No API key, no
credentials in this repository, no marginal cost per run.

---

## 1. The user and the bottleneck

**Who.** A tech lead or maintainer on a team that has adopted AI coding
assistants.

**The bottleneck.** Their repository is filling with generated tests. Coverage
climbs every sprint, CI stays green, review time goes up — and nobody can say
which of those thousands of assertions would actually catch a regression. The
failure is quiet and specific: a test written by reading the implementation can
repeat *what the code currently does*, including an existing mistake. It can
pass and raise coverage without necessarily adding useful fault detection.

There is no routine way to tell those tests apart from real ones. Coverage
cannot: it measures which lines were executed, not whether any assertion would
have objected to a different answer. So the lead is left choosing between
merging tests they cannot vouch for and hand-auditing generated code line by
line, which is slower than writing the tests themselves.

**Why it matters.** The whole value of a regression suite is the alarm it raises
on the day someone breaks something. A suite full of tests that cannot fail is
worse than a small honest one, because it is *believed*.

### The problem is real on a serious, human-written codebase

Placebo's subject is [`python-semver`](https://github.com/python-semver/python-semver)
at tag `3.0.4` — a widely used, BSD-3-Clause library whose maintainers hold it to
**100.0% line and branch coverage**.

Placebo injects 185 small, single-token faults into `semver/version.py` and runs
the project's own 329-test suite against each one:

| suite | tests | line + branch coverage | faults detected |
|---|---:|---:|---:|
| semver's own expert suite | 329 | **100.0%** | **96.2%** (178/185) |

That last column is the number coverage cannot give you. Even an excellent,
human-written suite at full coverage misses 7 injected faults. Independent
triage in `artifacts/survivor_triage.json` confirms that 6 are behaviorally
detectable gaps and 1 is an equivalent mutant in dead code.

---

## 2. What Placebo does

1. **Enumerate faults.** A deterministic AST mutation engine produces minimal,
   single-token edits (boundary flips, boolean swaps, constant and return-value
   changes) with content-derived ids, so the fault inventory is stable across
   machines and runs.
2. **Find candidate gaps.** Run the suite against each fault. A *survivor* means
   the evaluated suite did not distinguish the mutated program. Placebo then
   separates confirmed detectable gaps from equivalent or unresolved mutants.
3. **Author a test for each gap.** The agent is given the function and the
   one-line fault diff, and proposes a test.
4. **Admit only what execution proves.** A candidate is accepted only if it
   passes on clean `HEAD`, fails on the targeted fault, survives static
   anti-cheating checks, and is stable on repeat. Everything else is rejected
   with a structured code.
5. **Score on faults it never saw.** Results are reported on **held-out**
   mutants drawn from the same functions but different source spans, with
   same-line siblings excluded. The pre-generation manifest contains 29
   stratified faults; the authoritative report also scores every one of the 80
   eligible faults, eliminating sampling choice at the cost of being a
   post-generation analysis. Both fingerprints and exact manifests ship.

The final artifact is a review-ready test file where every test carries the
specific injected fault it was execution-verified to detect. A human still
decides whether that fault represents behavior worth preserving.

### Auditing tests, not just generating them

Generating a test that kills a mutant is the easy half. The reviewer's real
question is different, and coverage cannot answer it:

> Of the tests in this patch, which ones detect a failure that nothing else
> already detects?

A test that kills faults is still worthless if every fault it kills is already
killed by another test. Value is therefore **counterfactual**, not absolute:

```
value(t) = faults detectable with t  -  faults detectable without t
```

`placebo audit` computes this per test against two references simultaneously —
the repository's existing suite, and the sibling tests in the same patch — and
classifies each test:

| verdict | meaning |
|---|---|
| `VALUABLE` | sole detector of a fault the existing suite misses |
| `REDUNDANT_WITH_SIBLING` | detects a real gap, but a sibling detects it too |
| `REDUNDANT_WITH_EXISTING` | only re-detects what the repo already catches |
| `UNPROVEN` | no marginal sensitivity **under the evaluated fault models** |
| `HARMFUL` | red or unstable against correct code |

`UNPROVEN` is deliberately not "this test is useless". It is a statement about
what was measured, not about the test's intent.

The audit is efficient because pytest names the tests that failed: injecting one
fault and running the suite once yields an entire **column** of the kill matrix.
That reduces launches from tests x faults to one launch per fault; wall time
still grows with the underlying suite's runtime.

**Validation that the audit discriminates.** Run against two patches whose
character is known in advance, it separates them cleanly:

| patch | authored against | audit verdict |
|---|---|---|
| `placebo_D` | faults the existing suite already detects | **7/7 REDUNDANT** |
| `real_gap_patch` | the 6 confirmed real gaps | **3/3 VALUABLE** |

An audit that called everything valuable would be worthless. This one does not.

### Closing every real gap: the model was never the bottleneck

After oracle grounding removed wrong expected values, one failure mode was left:
the agent chose inputs that did not separate correct code from the fault. Of the
six confirmed gaps in semver's own suite, Placebo's agent closed three and
missed three — all three for that reason.

Searching an input space is not a language task. It is enumeration. So the
search was taken away from the model entirely and given to a deterministic,
cost-ordered enumerator over a boundary-heavy input domain, run differentially
against clean and faulty code, shrinking to the simplest distinguishing input.

| approach | real gaps closed | model calls | wall time |
|---|---:|---:|---:|
| agent with oracle grounding | 3 / 6 | 13 | 512 s |
| **+ deterministic counterexample search** | **6 / 6** | **0** | **95 s** |

Zero model calls. Every gap closed. The existing 329-test suite stays green, and
each generated test is admitted only after execution shows it passes on clean
code and fails on its specific fault.

The witnesses the search found are ones the model never proposed:

```python
semver.Version.parse("0.0.0").match(">=0.0.0")            # True  -> False
semver.Version.parse("0.0.0+0").is_compatible(...)        # True  -> False
semver.Version.parse(3.14)                                # message differs only
```

That last witness is a useful sensitivity example: both versions raise
`TypeError`, so `pytest.raises(TypeError)` cannot tell them apart. Checking the
observed message distinguishes them. It is not automatically a good product
requirement—exception text can be brittle—so Placebo presents it for human
review instead of treating admission as permission to merge.

### Evidence beyond injected faults

Mutation score is a proxy, so the project does not rest on it alone. Four
independent checks, none of which uses a language model:

| check | what it tests | result |
|---|---|---|
| **Real historical bugs** | defects that actually shipped in semver 3.0.4 and were fixed upstream later; ground truth is the maintainers' own diff and issue number | witness found for **3/3** behavior-changing bugs; **0/3** detected by semver's own suite |
| **Second repository** | the identical pipeline on `inflection` (string transformation, 455 tests) rather than version comparison | mutation scores differ substantially between subjects |
| **Metamorphic oracle** | properties asserting relationships, hardcoding no expected value | 12/12 sound on clean code; detects 1/6 gaps |
| **Run-to-run variance** | three stored independent runs of one condition | admitted 5/5/5 (CI [5.0, 5.0]); retry recoveries 1/0/2 (CI [0.0, 2.0]) |

Two of these deserve emphasis because they cut *against* convenient claims.

**The oracle trade-off went against expectation.** Metamorphic properties are
the stronger oracle — they cannot encode a pre-existing bug as expected — and
they are the *weaker* detector: 1/6 gaps versus 6/6 for snapshot witnesses.
Neither dominates. Both are reported.

**Variance shows the outcome is stable and the mechanism is not.** Admitted
counts were identical across three runs; retry recoveries swung from 0 to 2
under nominally identical settings. That asymmetry is exactly why the retry loop
is reported as unproven rather than as a contribution.

**One external validation worth noting.** Placebo's equivalent-mutant triage
concluded that a mutant in `bump_build` sits in dead code and cannot be killed.
Upstream reached the same conclusion independently: issue **#463**, fixed in
January 2025, removes that duplicated block. The historical-bug harness confirms
it from the other direction by finding no behavioral witness for that commit.

### Two evaluations, kept deliberately separate

The controlled **authoring benchmark** uses 12 known-detectable faults, paired
across every condition, and grades frozen suites on faults hidden from the
generator. These 12 faults are a test-authoring benchmark; they are not claimed
to be gaps in semver's expert suite.

The **real-gap closure runs** start from the 6 behaviorally confirmed faults
that actually survived semver's 329-test suite. The agent-only run closed 3/6;
the later deterministic counterexample search closed 6/6. See
[`experiments/real_gap_closure.json`](experiments/real_gap_closure.json),
[`experiments/gap_search.json`](experiments/gap_search.json), and
[`artifacts/suites/search_gap_patch.py`](artifacts/suites/search_gap_patch.py).

---

## 3. Results

See [`artifacts/report.md`](artifacts/report.md) for the generated tables, and
[`experiments/results.json`](experiments/results.json) for the raw numbers behind
every claim.

The **primary confirmatory result** uses the 29-fault manifest frozen before
generation: oracle-grounded Placebo detected **9/29 (31%)**, versus **0/29** for
the direct-prompt baseline. The independently useful all-eligible robustness
analysis gives the same 31% headline on 80 faults:

| condition | retained tests | held-out faults detected |
|---|---:|---:|
| direct-prompt baseline | 0 | 0/80 (0%) |
| fault shown, one attempt | 3 | 6/80 (8%) |
| fault shown + verification retries | 5 | 15/80 (19%) |
| implementation withheld | 4 | 14/80 (18%) |
| **oracle-grounded Placebo** | **7** | **25/80 (31%)** |

The zero-test baseline is a measured limitation of this local 7B model, not an
oracle-filtered strawman: all 12 first candidates were offered to the suite;
one was malformed and the other 11 failed on correct code. The baseline was
allowed to retain every clean candidate, while Placebo retained only candidates
with two-sided execution evidence.

On the end-to-end repository task, deterministic counterexample search produced
a six-test patch that remained green with all 329 existing tests and closed
**6/6 confirmed gaps (100%)**, with zero model calls. The earlier agent-only
three-test patch closed 3/6 and remains as an intermediate changelog artifact,
not the final result. Its evidence bundle can be rebuilt and independently
replayed with:

```bash
python scripts/build_bundle.py --real-gaps --out artifacts/real-gap-bundle
python scripts/verify_bundle.py --bundle artifacts/real-gap-bundle
```

### Acceptance criteria and the challenging case

A usable run must satisfy three gates: every shipped test stays green on clean
code, the final condition beats the same-model direct-prompt baseline on the
frozen confirmatory set, and the resulting patch closes at least one manually
confirmed repository gap without changing production code. Placebo met all
three. The reported 6/6 is completeness only for this manually triaged six-gap
set, not evidence that the repository has no other faults.

The hardest cases were two `Version.is_compatible` boundary mutants and a
`Version.parse` arithmetic mutant. Across three attempts per case, the agent's
proposed inputs never distinguished clean from faulty behavior, so all three
were rejected as `TARGET_MUTANT_SURVIVED`. That failure led to the deterministic
counterexample search above, which closed all three and then all six confirmed
gaps. The highest-value next capability is no longer more search for semver; it
is validating transfer on pinned external repositories and historical bugs.

---

## 4. Improvement changelog

Every row is an experiment that was actually run, with the evidence that decided
what happened next. Two of them are negative results that changed the design.

| # | What was tried, and why | Evidence | Decision |
|---|---|---|---|
| **Baseline** | Direct prompt: show the function, ask for a test. What a developer gets from an assistant today, then keeps whatever passes. | 12 tests offered, **0 retained**, 0/29 confirmatory and 0/80 all-eligible. Eleven failed against correct code (for example, calling nonexistent `semver.cmp_prerelease_tag` or preserving prerelease data that `bump_minor` drops); one was malformed. Outputs were 170–538 tokens against a 900-token cap, so none was truncated — see `artifacts/report.md` "Candidate disposition". | Established the floor. A direct prompt produced twelve plausible-looking candidates, none mergeable after one clean execution. |
| **1** | **Mutation-guided context.** Show the agent the one-line diff of a known-detectable evaluation fault. Isolates *context* as the variable. | 3/12 admitted; 4/29 confirmatory and 6/80 all-eligible faults detected | **Kept.** Targeting a concrete behavioral difference beats asking for "more tests". |
| **2a** | **Verification retry loop.** Feed structured rejection codes back and allow 3 attempts. | 5/12 admitted; 5/29 confirmatory and 15/80 all-eligible; 2.4× one-shot model time | **Investigated.** More tests helped the broader set, but the confirmatory gain was only one fault. |
| **2b** | **Diagnosis.** Most rejections were `CLEAN_HEAD_FAILED` — the model asserting a wrong expected value. The loop used pytest with `--tb=no`, so feedback lacked assertion detail; this was fixed to `--tb=short`. | Three stored B runs each admitted 5/12, but retry recoveries varied **0, 1 and 2** despite fixed settings | **Learning.** Better feedback helps sometimes, but retry benefit is small and stochastic; it is not the main contribution. |
| **3** | **Contract grounding.** Withhold the implementation body; the agent writes against the signature and docstring, so it cannot copy current behavior. | 4/12 admitted; 6/29 confirmatory but 14/80 all-eligible | **Mixed.** It improved the frozen sample but regressed slightly on the broader analysis; isolation also removed useful context. |
| **4** | **Oracle grounding.** Since the dominant failure was *guessing a value that can be computed*, stop asking for it. The model proposes only input expressions; those are executed against clean `HEAD` and against the fault; the assertion is synthesized from what clean `HEAD` actually returned, keeping only expressions that genuinely differ. | 7/12 admitted; **9/29** confirmatory and **25/80** all-eligible; `CLEAN_HEAD_FAILED` eliminated entirely | **Kept.** It wins on both sets and removes an entire failure class by construction rather than prompting. |
| **5** | **Marginal-value audit.** Generating tests answers the easy question. The reviewer's question is counterfactual: which test detects something nothing else detects? Score every test against the existing suite *and* its siblings. Pytest names which tests failed, giving a whole kill-matrix column per fault launch; total runtime still depends on suite speed. | Audited 33 agent-written tests against 185 faults: **1** sole detector, 3 sibling-redundant, 18 already covered by the repo, 11 red on clean code. Minimized 33 -> 2 tests detecting **the same 3 faults**, verified by re-execution. | **Kept, and it reframed the project.** Placebo audits tests rather than only generating them. |
| **5b** | **Bug found by the audit's own output.** The first minimizer kept only `VALUABLE` tests. But when several siblings detect one fault, each is "redundant" and dropping all of them loses the fault outright. | Reported 3 gaps closed but a 1-test minimized patch — an arithmetic impossibility that exposed the bug | **Fixed.** Minimization is now a greedy set cover over novel faults, with three regression tests and post-hoc verification by re-execution. |
| **6** | **Deterministic counterexample search.** The remaining failure was input search, not value prediction. For the semver adapter, enumerate a hand-designed boundary-heavy domain, evaluate every candidate differentially against clean and faulty code, and shrink to the simplest input that separates them. The model is not involved in this run. | Real-gap closure **3/6 -> 6/6**, with **0 model calls** and 95.5 s wall time. Found witnesses the agent never proposed, including an error-message-only fault invisible to `pytest.raises(TypeError)`. | **Kept.** The single largest improvement in the project, and it removed the model from the loop rather than adding to it. |
| **Removed** | **Contract-only isolation as the final architecture.** It was intended to stop implementation copying, but hid context the input-search agent needed. | 6/29 beat B on the frozen set, while 14/80 trailed B's 15/80 and D reached 25/80 | **Removed from the final configuration.** D keeps implementation context but removes value prediction from the model. |

---

## 5. Main failure mode

Full detail in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md), written to help a
reviewer find the weak points rather than to list strengths.

**Placebo measures a proxy.** Mutation score is not real-fault detection.
Single-token mutants are not distributed like real bugs, some survivors are
*equivalent mutants* that no test can kill, and a suite tuned to kill mutants
could in principle overfit to the operator set. Placebo mitigates this: the
29-fault confirmatory set was frozen before generation; every scored fault is
known-detectable by the expert suite; and same-line siblings are excluded. The
80-fault all-eligible result is transparently labeled post-generation. This does
not eliminate proxy risk. All 7 survivors of semver's own suite were manually triaged
through the same execution oracle: 6 are confirmed detectable gaps and 1 is an
equivalent mutant. The raw 96.2% and equivalence-adjusted 96.7% scores are both
reported.

**Nondeterminism.** Ollama with partial GPU offload is not bitwise
deterministic even at `temperature=0` with a fixed seed. Identical first attempts
produced different outputs across two runs. Admission verdicts are deterministic
(they are pytest runs); model outputs are not. Reported figures are single runs
and should be read with that variance in mind.

## 6. Hot take

**Don't ask a language model to search. Ask it what to search for.**

The two largest gains in this project both came from *removing* work from the
model, and both were found by reading rejection codes rather than by intuition.

First, it was guessing return values the implementation could simply be executed
to obtain — 86% of failures, eliminated by construction. Then, with that fixed,
it was guessing *inputs*: the agent closed 3 of 6 real gaps. A deterministic
enumerator over the same input space closed **6 of 6, with zero model calls, in
95 seconds**.

The model is good at knowing which input domain is worth exploring. It is bad at
exploring it. Those are different jobs, and giving both to the same component is
why so much agent engineering underperforms.

**Corollary: don't count tests. Account for them.**

Every metric in common use — test count, coverage, even mutation score — is a
*total*. Totals cannot tell you whether a test earns its place, because the
question is counterfactual: *what failure becomes detectable only because this
test exists?*

The measurement is uncomfortable. Auditing 33 tests this project's own agents
wrote, against 185 fault models:

| verdict | count |
|---|---:|
| sole detector of a fault the existing suite misses | **1** |
| detects a real gap, but a sibling detects it too | 3 |
| only re-detects what the repository already catches | 18 |
| red or unstable against correct code | 11 |

Thirty-three tests. Two are needed. The minimized patch detects **the same 3
faults** as the full patch, verified by re-execution — a 94% cut in review
burden with no loss of protection. A suite can grow indefinitely while its
ability to catch a regression does not move at all, and nothing on a normal
dashboard would show it.

**Never let a language model guess a value you can compute.**

The single largest improvement in this project was not a better prompt, a bigger
model, more retries, or another agent. It was noticing — from rejection-code
data, not intuition — that 86% of failures were the model predicting a return
value that the correct implementation was sitting right there ready to tell us.
Removing that responsibility from the model eliminated the entire failure class.

The corollary is the uncomfortable half: a retry loop feels like engineering,
but its benefit here was small and unstable — zero to two recovered cases across
three stored runs. Feedback only helps when the model can act on it. Keep a
bounded retry as a safety net, measure it, and prefer removing an unnecessary
decision from the model over asking it more politely.

---

## 7. What existed before this competition

| Component | Origin |
|---|---|
| `subject/` — semver 3.0.4 source and its 329 tests | **Third party.** BSD-3-Clause, vendored at pinned commit `6adf876`. See [`subject/PROVENANCE.md`](subject/PROVENANCE.md). Unmodified except two git symlinks materialized as files on Windows. |
| `qwen2.5:7b` via Ollama | **Third party.** Off-the-shelf local model, unmodified, not fine-tuned. |
| pytest, pytest-cov, coverage | **Third party.** Pinned in `requirements.lock`. |
| `src/placebo/**` — mutation engine, oracle runner, admission gates, held-out split, prober, agent, evaluator | **Written for this competition.** |
| `scripts/**`, `tests/**`, all experiments, manifests and reports | **Written for this competition.** |

Placebo's engine depends only on the Python standard library (`ast`,
`tokenize`, `subprocess`, `hashlib`). No mutation-testing framework is used:
`mutmut` requires `os.fork()` and cannot run on Windows, and both it and
`cosmic-ray` address mutants by session ordering, which cannot be frozen into a
reproducible held-out split.

## 8. Safety and scope

- The agent never modifies production code. A patch-scope gate rejects any
  candidate touching anything outside the generated-test path, and the runner
  restores the original file after every mutation.
- All execution happens in a disposable workspace copy of the subject, never in
  the source tree.
- Static gates reject candidates using `subprocess`, sockets, `urllib`, `eval`,
  `exec`, mocking, source inspection, or `skip`/`xfail`.
- The oracle accepts only an AST-validated `semver` expression DSL and executes
  it in a disposable subprocess with Python builtins disabled. A production
  deployment should additionally use a networkless OS container.
- Output is a **proposed test patch for human review**, never an automatic
  merge. The tech lead is the decision-maker; Placebo supplies the evidence.
- The subject is public, permissively licensed code. No private data, no
  credentials, no personal information.

## 9. Reproduction

See [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) for exact commands, versions,
runtimes and expected output from a clean environment.

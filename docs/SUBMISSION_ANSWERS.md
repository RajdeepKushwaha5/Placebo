# Submission form answers

Copy the relevant block into each field. Every number here is backed by a file
in the repository, listed at the end.

---

## Project name

Placebo

## Tagline (one line)

Your test suite got bigger. Placebo tells you whether it got better.

## Short description (2 to 3 sentences)

Placebo audits AI-generated tests and tells a reviewer which ones actually earn their place. It measures what each test would catch that nothing else already catches, then proposes a smaller patch where every test carries executable evidence for the specific fault it detects. It runs on a 7B model on a laptop GPU, with no API key and zero cost per run.

---

## Who has this problem?

A tech lead or maintainer on a team that has adopted an AI coding assistant.

Their repository fills with generated tests every sprint. Test count goes up, coverage goes up, CI stays green, and nobody on the team can say which of those thousands of assertions would actually catch a regression. The lead ends up choosing between merging tests they cannot vouch for and hand-auditing generated code line by line, which takes longer than writing the tests themselves.

This is not a niche problem. Any team using Copilot, Cursor or Claude Code to write tests has it right now, and the volume only grows.

## What bottleneck makes it worth solving?

The failure is quiet and specific. When an assistant writes a test, it reads the implementation first and then records what the implementation already does. If the code is correct, the test passes. If the code is wrong, the test records the wrong answer and still passes. Either way it goes green, and either way coverage goes up.

A test written that way cannot fail. A test that cannot fail cannot warn anyone about anything.

Coverage cannot detect this, because coverage only measures which lines executed. It never asks whether any assertion would have objected had the answer come back wrong.

To prove this is real rather than theoretical, I took `python-semver` 3.0.4, a widely used library whose maintainers hold it at 100 percent line and branch coverage. I injected 185 single-character faults and ran their own 329 tests against every one. The suite caught 178. Seven got through at full coverage. Manual triage confirmed six are genuinely detectable gaps and one is an equivalent mutant in dead code.

So the bottleneck is that the industry's standard quality signal is blind to the exact failure mode that AI-generated tests introduce at scale.

## Does the agent solve it well?

Three results, each independently verifiable.

**It audits, and the audit discriminates.** Run against 33 tests my own agents wrote, unedited, Placebo found that exactly 1 adds unique fault detection. Eighteen only re-detect faults the repository already catches, three duplicate a sibling in the same patch, and eleven do not even pass against correct code. It then shrinks the patch from 33 tests to 2 while still detecting the same three faults, and re-runs the entire audit on the reduced patch to prove nothing was lost instead of asserting it. An audit that called everything valuable would be worthless, so I checked it against two patches whose character was known in advance: it scored 7 of 7 redundant on one and 3 of 3 valuable on the other.

**It closes real gaps, and the model turned out not to be the bottleneck.** With oracle grounding, the agent closed 3 of the 6 confirmed gaps in semver's suite. Reading the rejection codes showed the remaining failure was input choice, not test writing. So I took the search away from the model and gave it to a deterministic enumerator. That closed 6 of 6, with zero model calls, in 36 seconds, and the original 329 tests still pass. It found inputs the model never proposed, including a fault where both versions raise the same TypeError and only the message differs, which `pytest.raises(TypeError)` structurally cannot catch.

**It works on real bugs, not just injected ones.** Mutation score is a proxy, so I went through semver's actual git history for defects that shipped in 3.0.4 and were fixed upstream later, using the maintainers' own diffs and issue numbers as ground truth. The search found a distinguishing input for all three behavior-changing bugs. Semver's own 329 tests catch none of them. The fourth commit removes dead code, so finding no witness there is the correct answer, and it independently confirms an equivalent-mutant verdict Placebo had reached from the opposite direction.

In the controlled comparison, scored on 29 faults frozen and fingerprinted before any generation ran, the direct-prompt baseline detected 0 percent and the best configuration detected 31 percent.

## Can another person reproduce the result?

Yes, and the central claim needs no GPU and no API key.

```
git clone https://github.com/RajdeepKushwaha5/Placebo.git
cd Placebo
python -m pip install -r requirements.lock
python scripts/run_census.py --workers 6
```

That takes about two minutes and prints 185 faults, 178 detected, 96.2 percent. Three pinned dependencies, no credentials anywhere in the repository, and Placebo's own engine imports only the Python standard library.

Everything that does not need a model is reproducible the same way: the counterexample search (6 of 6, 36 seconds), the real historical bugs (3 of 3, 1 second), the second repository, the metamorphic oracle and the variance analysis.

Reproducibility is also enforced rather than promised. `scripts/check_consistency.py` re-derives all 102 headline numbers from the stored artifacts and fails if the writeup drifts from the data. It runs in CI, so a stale number becomes a build failure instead of something a reviewer has to notice. It is what caught a report contradicting its own raw results during development.

Both evidence bundles replay independently: `python scripts/verify_bundle.py` re-applies each recorded fault and re-runs the test that claims to detect it, reporting HOLDS or BROKEN per test.

---

## What makes this different from existing work

Mutation-guided test generation is not new. Meta's ACH does it at scale. If I submitted "LLM generates tests, verifier checks them", a knowledgeable judge would correctly call it a smaller version of existing work.

The contribution is the reframe. Placebo does not primarily generate tests, it audits them, and the question it asks is counterfactual rather than absolute:

```
value(test) = faults detectable with it  minus  faults detectable without it
```

A test that kills mutants is still worthless if every fault it kills is already killed by something else. That distinction produces four actionable verdicts (valuable, redundant with a sibling, redundant with the existing suite, no demonstrated sensitivity) plus a fitness verdict for tests that are simply broken. Nothing I found does per-test marginal attribution against both the existing suite and sibling tests at once.

The second contribution is negative and more useful than it sounds: for the hardest step, the language model was the wrong tool, and removing it improved the result.

---

## How I built it

Deterministic AST mutation engine with content-derived fault identities, so a held-out split can be frozen and fingerprinted. An oracle runner that executes the suite against one fault at a time in a disposable workspace. Admission gates that accept a test only when execution proves it passes on correct code and fails on its specific fault. A marginal-value auditor that gets an entire column of the kill matrix from one execution, because pytest reports which tests failed. A deterministic counterexample search. Two evidence bundles that replay offline.

I wrote the mutation engine rather than using mutmut or cosmic-ray for two reasons. Mutmut needs `os.fork()`, which does not exist on Windows, and standardising on Docker purely to get a mutation tool would raise the bar for anyone reproducing the work. More importantly, both tools identify mutants by session ordering, and a held-out split cannot be frozen against an identifier that changes between runs.

---

## Biggest challenge

The hardest part was not building anything, it was noticing that my instincts were wrong twice.

I added a verification retry loop because feeding failures back to the model felt obviously right. It cost 2.4 times the compute and recovered almost nothing. I then found the loop was running pytest with `--tb=no`, so the feedback carried no assertion detail at all. I fixed that, showed the model the exact correct value, and it still could not repair its own test. Three stored runs recovered 0, 1 and 2 cases under identical settings, so I report the retry loop as unproven rather than as a contribution.

The second was assuming the model needed better prompting to find the remaining gaps. It did not. It needed to stop searching.

---

## What I learned

Do not ask a language model to search. Ask it what to search for.

Both of my largest gains came from taking work away from the model, and both were found by reading rejection-code distributions rather than by intuition. First it was guessing return values that the implementation could simply be executed to obtain, which was 18 of 21 rejections and was eliminated by construction. Then it was guessing inputs, where a deterministic enumerator beat the agent 6 to 3 with zero model calls.

A language model is good at knowing where to look and bad at looking. Those are different jobs, and handing both to the same component is why a lot of agent engineering underperforms.

The corollary, and the reason the audit exists: do not count tests, account for them. Every metric in common use is a total, and totals cannot tell you whether a test earns its place.

---

## What went wrong, honestly

The minimizer had a bug, and the tool caught it in its own output. It reported three faults covered alongside a one-test patch, which is arithmetically impossible. When several sibling tests detect the same fault each one looks redundant, so dropping all of them loses the fault outright. Minimization is a set-cover problem, not a filter. Fixed, with three regression tests and post-hoc verification by re-execution.

I also found that `--faults N`, a documented flag, could invert an audit verdict by truncating the corpus in source order and dropping exactly the faults that matter. The same patch scored 0 valuable at one setting and 3 valuable on the full corpus. Fixed so known gaps are always retained.

---

## Limitations I am not hiding

Expected values are observed by running the current code, so they pin behavior rather than correctness. If the implementation is already wrong, a witness records the wrong answer as expected. This is the sharpest limitation in the project and it is documented in full.

Two Python libraries is a narrow base. Four real bugs is not four hundred. Most conditions are single runs, and only one has error bars. The best configuration uses more model calls than the baseline, and while a resampling control is implemented, any result from it appears in the artifacts or is not claimed at all.

A blinded reviewer study is prepared with patches stripped of condition markers, a rating form and a pre-registered analysis. No ratings have been collected and no human acceptance rate is claimed anywhere.

`docs/LIMITATIONS.md` is written to help a reviewer find weak points rather than to list strengths.

---

## Tools and AI disclosure

**Coding agent:** Claude Code (Anthropic) was used throughout for implementation, debugging and writing. Full trajectories are in `trajectories/`, including every model call with prompts, responses, token counts and durations.

**Model inside the product:** `qwen2.5:7b`, quantisation Q4_K_M, served locally by Ollama at temperature 0 with seed 7. Off the shelf, unmodified, not fine-tuned. It runs on an RTX 3050 laptop GPU with 4 GB of VRAM, so the model is partially offloaded to CPU at roughly 6 tokens per second.

**Third-party code:** `python-semver` 3.0.4 (BSD-3-Clause) and `inflection` 0.5.1 (MIT), both vendored at pinned commits with provenance files. pytest, pytest-cov and coverage, pinned in `requirements.lock`. Everything under `src/`, `scripts/` and `tests/` was written for this competition.

No API keys, no hosted model calls, no credentials in the submission, and zero marginal cost per run.

---

## Links

- **Repository:** https://github.com/RajdeepKushwaha5/Placebo
- **Start here:** `SUBMISSION.md` maps every claim to the file that proves it
- **Generated report:** `artifacts/report.md`
- **Visual evidence:** `artifacts/evidence.html`, self-contained, opens offline

---

## Every number, and where it is proved

| Claim | File |
|---|---|
| 100 percent coverage, 96.2 percent fault detection, 7 missed | `artifacts/census_summary.json` |
| 6 real gaps, 1 equivalent mutant | `artifacts/survivor_triage.json` |
| 33 tests audited, 1 valuable, minimized to 2 with no loss | `experiments/audit.json` |
| 6 of 6 gaps closed, 0 model calls, 36 seconds | `experiments/gap_search.json` |
| 3 of 3 real historical bugs found | `experiments/historical_bugs.json` |
| Second repository, 85.5 percent versus 96.2 percent | `experiments/multirepo_census.json` |
| 12 metamorphic properties sound, detect 1 of 6 | `experiments/metamorphic.json` |
| Run-to-run variance and bootstrap intervals | `experiments/variance.json` |
| Held-out comparison, 0 percent versus 31 percent | `experiments/results.json` |

Verify all of it in three minutes:

```
python -m pytest tests             # 359 passed
python scripts/check_consistency.py   # 102/102 checks pass
```

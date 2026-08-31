# Placebo — results

- **Subject**: `semver` @ `6adf8765f6e2`, `semver/version.py`
- **Model**: `qwen2.5:7b` (local, temperature 0, seed 7)
- **Discovery mutants**: 12 (shown to the agent)
- **Held-out faults (all-eligible robustness analysis)**: 80 — every eligible fault, with no per-function cap, so the sample has no tunable parameter. Materialized after generation as an all-eligible analysis; never shown to the agent. Fingerprint `cb088e4cd91a408c`
- **Held-out faults (primary confirmatory set)**: 29 — the pre-generation, frozen stratified sample of 3 per function, retained as the strict confirmatory check. Fingerprint `491a2c1f8af0ef27`

## Candidate disposition (baseline fairness audit)

| condition | offered | parse/shape excluded | failed clean repair | retained |
|---|---:|---:|---:|---:|
| `baseline_A` | 12 | 1 | 11 | 0 |
| `mutant_aware_B1` | 3 | 0 | 0 | 3 |
| `placebo_B` | 5 | 0 | 0 | 5 |
| `placebo_C` | 4 | 0 | 0 | 4 |
| `placebo_D` | 7 | 0 | 0 | 7 |

The direct-prompt baseline is not filtered by fault detection: every candidate is offered, and every candidate that passes correct code is eligible to remain. Placebo conditions additionally require two-sided oracle admission.

## Reference: what the subject's own expert suite achieves

| suite | tests | line coverage | mutation score |
|---|---:|---:|---:|
| semver's human-written suite | 329 | 100.0% | **96.2%** (178/185) |

> A suite at **100% line and branch coverage** still fails to detect 7 of 185 injected faults. Coverage measures what the tests *touched*, not what they would *catch*.

All 7 survivors were triaged by hand against the same oracle (`scripts/triage_survivors.py`): **6 are confirmed real gaps**, each with a verified killing test, and 1 is a genuine equivalent mutant sitting in dead code that mutation testing surfaced and 100% coverage did not. Equivalence-adjusted score: **96.7%**.

## Held-out comparison

All conditions use the same model, seed, discovery mutants, held-out faults, evaluator and model-free green-test repair. The suite-policy column makes the intentional baseline/Placebo admission difference explicit; the remaining experimental variable is the scaffolding.

| condition | suite policy | tests | admitted | **confirmatory kill (n=29)** | all-eligible (n=80) | line cov | model s |
|---|---|---:|---:|---:|---:|---:|---:|
| `baseline_A` | all green candidates | 0 | 0/12 | **0%** (0/29) | 0% (0/80) | 0.0% | 613 |
| `mutant_aware_B1` | oracle-admitted only | 3 | 3/12 | **14%** (4/29) | 8% (6/80) | 46.7% | 181 |
| `placebo_B` | oracle-admitted only | 5 | 5/12 | **17%** (5/29) | 19% (15/80) | 52.7% | 440 |
| `placebo_C` | oracle-admitted only | 4 | 4/12 | **21%** (6/29) | 18% (14/80) | 49.7% | 849 |
| `placebo_D` | oracle-admitted only | 7 | 7/12 | **31%** (9/29) | 31% (25/80) | 52.5% | 1040 |

## Primary metric

**Pre-generation confirmatory mutation score, best condition (`placebo_D`) vs. direct-prompt baseline (`baseline_A`):**

- baseline_A : 0%
- placebo_D : 31%
- **absolute change: +31 percentage points**

## Coverage does not track fault detection

| condition | line coverage | held-out kill |
|---|---:|---:|
| `baseline_A` | 0.0% | 0% |
| `mutant_aware_B1` | 46.7% | 14% |
| `placebo_B` | 52.7% | 17% |
| `placebo_C` | 49.7% | 21% |
| `placebo_D` | 52.5% | 31% |

## What each condition changes

| condition | scaffolding |
|---|---|
| `baseline_A` | Direct prompt. Function source only, no fault shown, no retry. |
| `mutant_aware_B1` | Shown a known-detectable evaluation fault. One attempt, no retry loop. |
| `placebo_B` | Shown the fault + verification retry loop (3 attempts). |
| `placebo_C` | Implementation body withheld; tests written against the contract. |
| `placebo_D` | Oracle-grounded: model picks inputs, execution supplies values. |

## Cost

| condition | model calls | output tokens | model seconds | USD |
|---|---:|---:|---:|---:|
| `baseline_A` | 12 | 3976 | 613 | $0.00 |
| `mutant_aware_B1` | 12 | 1231 | 181 | $0.00 |
| `placebo_B` | 29 | 2819 | 440 | $0.00 |
| `placebo_C` | 28 | 2970 | 849 | $0.00 |
| `placebo_D` | 23 | 5173 | 1040 | $0.00 |

Local inference on a consumer laptop GPU: no API key, no marginal cost, no credentials in the submission.

## End-to-end real-gap closure

This product run is separate from the controlled authoring benchmark. It starts only from faults that survived the repository's existing suite and were manually confirmed behaviorally detectable.

| existing tests | confirmed gaps | generated tests retained | union green | gaps closed |
|---:|---:|---:|:---:|---:|
| 329 | 6 | 3 | yes | **3/6 (50%)** |

## Marginal-value audit of agent-written tests

Coverage cannot answer the reviewer's actual question: *which of these tests detects a failure that nothing else already detects?* Each test is scored counterfactually against two references at once — the repository's existing suite, and its sibling tests in the same patch.

| patch | tests | valuable | redundant (sibling) | redundant (existing) | unproven | harmful | gaps closed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `as_generated_patch` | 33 | **1** | 3 | 18 | 0 | 11 | 3 |

### Minimization of `as_generated_patch`

- tests before: **33**
- tests after: **2**
- novel faults detected before: 3
- novel faults detected after: 3
- **no loss verified by re-execution: yes**

Minimization is a set cover over the faults only this patch detects, not a filter on per-test verdicts. Keeping only `VALUABLE` tests would drop any fault that several sibling tests detect — each looks redundant, yet removing all of them loses the fault. The reduced patch is re-audited by execution rather than trusted.

`UNPROVEN` means *no marginal fault sensitivity under the evaluated fault models* — not that the test is worthless. A test may encode a requirement no fault in the corpus expresses.

## Deterministic counterexample search on confirmed real gaps

After oracle grounding removed wrong expected values, the remaining failure was input search: the agent chose inputs that did not separate correct code from the fault. Searching an input space is enumeration, not a language task, so it was moved out of the model entirely.

| approach | real gaps closed | model calls | wall time |
|---|---:|---:|---:|
| agent with oracle grounding | 3/6 | 13 | 512 s |
| **+ counterexample search** | **6/6** | **0** | **36 s** |

Existing 329-test suite plus the generated patch stays green: **True**. The search is deterministic — a fixed, cost-ordered candidate pool with no sampling and no seed — so the same witnesses are found on every run.

Minimal witnesses found by search:

| fault | witness input | clean | under fault |
|---|---|---|---|
| `33797d243637` | `semver.Version.parse(3.14)` | `TypeError: not expecting type '<clas` | `TypeError: can't multiply sequence b` |
| `400588ba9c9f` | `semver.Version.parse("0.0.0+0").is_compatible(semver.Version.parse("0.0.0"))` | `True` | `False` |
| `7c644c64bde4` | `semver.Version.parse("0.0.0").match(">=0.0.0")` | `True` | `False` |
| `95f32034b4f9` | `semver.Version.parse("0.0.0").is_compatible(semver.Version.parse("0.0.0-alpha"))` | `False` | `None` |
| `a6eb2ad4fd72` | `semver.Version.parse("0.0.0").is_compatible(semver.Version.parse("0.0.0+0"))` | `True` | `False` |
| `bad59b17cefa` | `semver.Version.parse("0.0.0").match("<=0.0.0")` | `True` | `False` |

## Generalization: a second repository

semver is comparison- and boundary-heavy, exactly the shape these mutation operators target. `inflection` is string transformation logic with a different fault surface. The identical pipeline runs on both.

| subject | domain | existing tests | faults | undetected | mutation score |
|---|---|---:|---:|---:|---:|
| `inflection` | string transformation logic | 455 | 76 | 11 | **85.5%** |
| `semver` | version comparison and boundary logic | 329 | 185 | 7 | **96.2%** |

The scores differ substantially, which is the useful part: the method reports a property of each suite rather than a constant.

## Real historical bugs (not injected faults)

Mutation score is a proxy. These are defects that actually shipped in semver 3.0.4 and were fixed upstream afterwards, so the ground truth is the maintainers' own diff and issue number. `faulty` is the released source; `clean` is the upstream fix.

- behavior-changing bugs with a witness found: **3/3**
- detected by semver's own 329-test suite: **0/3** (all shipped at 100% coverage)
- behavior-preserving refactors correctly reported as indistinguishable: **1/1**
- model calls: **0**

| upstream issue | defect | witness input |
|---|---|---|
| `#460` | bump_prerelease does not always produce a newer version | `str(semver.Version.parse("0.0.0-alpha").bump_prerelease(""))` |
| `#469` | next_version does not bump build-only versions | `str(semver.Version.parse("0.0.0+0").next_version("major"))` |
| `#339` | next_version does not reset prerelease when token changes | `str(semver.Version.parse("0.0.0+0").next_version("major"))` |

Issue `#463` removes dead code, so finding **no** witness is the correct answer there. It independently confirms the equivalent-mutant verdict reached from the other direction in `artifacts/survivor_triage.json`.

## Oracle strength versus detection power

The default oracle records what the reference implementation returned - a level-4 snapshot, which cannot tell correct from *currently does this*. Metamorphic properties assert relationships between executions instead, hardcode no expected value, and so cannot inherit a pre-existing bug.

| oracle | hardcodes expected values | confirmed gaps detected |
|---|:--:|---:|
| level 4 - execution snapshot | yes | **6/6** |
| level 3 - metamorphic properties | **no** | 1/6 |

All 12 properties hold on clean code (`all_properties_sound_on_clean`: true).

> This is a genuine trade-off, reported rather than resolved. The stronger oracle is the weaker detector. Snapshot witnesses close every gap but pin behavior rather than correctness; metamorphic properties close far fewer but cannot encode an existing bug as expected.

## Run-to-run variance

Headline conditions are single runs. These are repeated runs of the same condition, so the spread is measured rather than assumed.

| condition | runs | admitted (median, range) | 95% CI | retry recoveries |
|---|---:|---|---|---|
| `placebo_B` | 3 | 5 (5-5) | [5.0, 5.0] | 1 (0-2) |

The asymmetry is the finding: **the outcome is stable, the mechanism credited for it is not.** Admitted counts do not move across runs; retry recoveries range from 0 to 2 under nominally identical settings. That is why no strong claim is made for the retry loop. Deterministic components - census, splits, search, admission - have no variance at all.

## Equal-budget control: is the gain just more model calls?

The best condition spends more model calls than the direct-prompt baseline, so the obvious objection is that the scaffolding did nothing and the extra attempts did the work. This gives the plain prompt the same budget as independent draws, then scores it two ways: what a developer would actually keep (the first candidate green against correct code), and the generous best-of-N reading (did any draw detect the fault at all).

| approach | model calls | faults detected |
|---|---:|---:|
| direct prompt, 3 independent draws | **36** | 3/12 |
| oracle-grounded scaffolding | **23** | 7/12 |

The resampled baseline used **more** model calls and detected **fewer** faults. Extra attempts are not the mechanism. Taking value prediction away from the model is.

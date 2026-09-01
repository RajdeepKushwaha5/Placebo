# Submission map

Where every required item lives, and how to check it yourself in about ten
minutes without a GPU or an API key.

## Start here (no model needed, ~3 minutes)

```bash
python -m pip install -r requirements.lock
python -m pytest tests -q                 # 38 passed
python scripts/check_consistency.py       # 77/77 checks pass
python scripts/verify_bundle.py --bundle artifacts/bundle          # 7/7 hold
python scripts/verify_bundle.py --bundle artifacts/real-gap-bundle # 3/3 hold
```

`check_consistency.py` re-derives every headline number from the stored
artifacts and fails if the writeup drifts from the data. It is the fastest way
to confirm nothing here is asserted rather than measured.

## The four required deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | **Solution code + improvement changelog** | this repository; changelog is [README section 11](README.md#11-improvement-changelog) |
| 2 | **Reproduction guide** | [`docs/REPRODUCTION.md`](docs/REPRODUCTION.md) ,  two paths, one needs no model |
| 3 | **Solution video** | submitted separately |
| 4 | **Agent trajectories** | [`trajectories/`](trajectories/) ,  6 rendered walkthroughs + raw JSONL of every model call |

Required narrative elements and where they live:

| element | location |
|---|---|
| Intended user and their bottleneck | README section 1 |
| Why solving it is valuable | README section 1 |
| Improvement changelog, evidence per row | README section 11 |
| Main failure mode | README section 12 |
| Hot take | README section 13 |
| What existed before the competition | `subject/PROVENANCE.md` and `subjects/inflection/PROVENANCE.md`, one per vendored dependency |
| Full limitations write-up | `docs/LIMITATIONS.md` |

## Headline results, and the file that proves each

| Claim | Evidence |
|---|---|
| semver's suite: 100% coverage, **96.2%** fault detection, 7 missed | `artifacts/census_summary.json` |
| 6 of those 7 are real gaps; 1 is an equivalent mutant in dead code | `artifacts/survivor_triage.json` |
| 33 agent-written tests → **1** adds unique detection, 11 are red | `experiments/audit.json` |
| Minimized 33 → 2 tests, same 3 faults, **verified by re-execution** | `experiments/audit.json` → `minimization` |
| Deterministic search closes **6/6** confirmed gaps, **0 model calls** | `experiments/gap_search.json` |
| **3/3** real historical bugs found; semver's own suite catches 0 | `experiments/historical_bugs.json` |
| Second repository (`inflection`): 85.5% vs semver's 96.2% | `experiments/multirepo_census.json` |
| Metamorphic oracle: 12 properties sound, detects 1/6 | `experiments/metamorphic.json` |
| Run-to-run variance: admitted stable, retry recoveries 0–2 | `experiments/variance.json` |
| Equal-budget control: 3/12 on 36 calls vs 7/12 on 23 | `experiments/equal_budget.json` |
| Repeated headline runs with bootstrap intervals | `experiments/seeds.json` |
| Run-to-run spread for one stored condition | `experiments/variance.json` |
| Held-out comparison: baseline 0%, best condition 31% | `experiments/results.json` |

Rendered together: [`artifacts/report.md`](artifacts/report.md) and the
self-contained [`artifacts/evidence.html`](artifacts/evidence.html).

## Packaging the archive

```bash
python scripts/package_submission.py
```

Writes `placebo-submission.zip` and verifies it before you upload: under the
size limit, all required deliverables present, no credentials, no workspace or
cache files. Current archive: **0.39 MB across 189 files**.

## The product surface

```bash
placebo gaps                                  # what the suite fails to detect
placebo audit <patch.py> --minimize           # which tests earn their place
placebo explain <test-name>                   # why does this test exist?
placebo verify --bundle artifacts/bundle      # re-check every claim
```

`gaps` and `explain` return instantly. `audit` runs the suite once per fault and
takes minutes on a real corpus.

## Ground rules

- **Human approval required.** Placebo proposes a test patch; it never merges,
  and it never edits production code. A patch-scope gate rejects any candidate
  touching anything outside the generated-test path.
- **Sandboxed.** All execution happens in a disposable workspace copy. The
  oracle probe runs an AST-validated expression subset with a builtins
  whitelist; imports, file access and process control are rejected.
- **No credentials.** Nothing here needs an API key. Inference is local.
- **Provenance.** Third-party code is isolated in `subject/` and `subjects/`
  with pinned commits and licences; see each `PROVENANCE.md`. Everything under
  `src/`, `scripts/` and `tests/` was written for this competition.

## Read this before judging the numbers

[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) is written to help you find the
weak points rather than to list strengths. The four that matter most:

1. **Expected values are a snapshot, not correctness.** They pin today's
   behavior. If the implementation is already wrong, a witness records the wrong
   answer as expected (§9).
2. **Mutation score is a proxy.** Partly offset by the real historical bugs, but
   four bugs is not four hundred (§1).
3. **Narrow base.** Two Python libraries, one small local model (§5, §6).
4. **Single runs.** See §3. `experiments/seeds.json` carries repeated runs of
   the headline conditions where they were completed; anything absent from that
   file was not run, and no interval is claimed for it.

Nothing in this repository claims a correctness proof. The artifacts are
executable witnesses: each shows a test passes on clean code and fails on one
specific named fault, and each is independently replayable.

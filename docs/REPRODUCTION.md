# Reproduction guide

Written for someone starting from a clean environment with this repository and
nothing else.

There are **two paths**. Path A reproduces the central result (that a
100%-coverage expert suite still misses real faults) and needs no model at all.
Path B reproduces the full agent comparison and needs a local model.

---

## 0. What you need

| | |
|---|---|
| Python | **3.13.0** (developed and measured on this; ≥3.11 should work) |
| OS | Windows 11 (developed on), Linux or macOS |
| Disk | ~100 MB |
| Network | Only to install the three pinned packages. Nothing at runtime. |
| API keys | **None.** There are no credentials in this repository and none are needed. |
| GPU | Optional. Only Path B uses a model. Measured on an RTX 3050 Laptop (4 GB). |

### Install

```bash
python -m pip install -r requirements.lock
```

That installs exactly:

```
pytest==9.0.2
pytest-cov==7.1.0
coverage==7.16.0
```

Placebo's own engine imports only the standard library.

### Verify the install

```bash
python -m pytest tests
```

Expected: **80 passed** in a few seconds. These cover mutant-identity stability,
held-out split disjointness, static admission gates, suite assembly, and the
malformed-candidate regression found during the final audit.

---

## Path A: the central result, no model required

**Runtime: ~2.5 minutes.** This is the claim that motivates the project, and it
is fully deterministic: no model is involved anywhere in it.

```bash
python scripts/run_census.py --workers 6
```

Lower `--workers` if you have fewer cores; it changes runtime, not results.

### What it does

Enumerates every single-token fault in `subject/semver/version.py`, then runs
semver's own 329-test suite against each fault, once per fault.

### Expected output

```
  mutants enumerated : 185
  scorable           : 185
  killed             : 178
  SURVIVED (triage)  : 7
  mutation score     : 96.2%
```

followed by the 7 survivors listed by id and source location. A survivor is a
candidate gap until equivalence triage; `python scripts/triage_survivors.py`
confirms 6 detectable gaps and 1 equivalent mutant for this subject.

Wall time on the development machine: **129 s** with 6 workers.

### Written artifacts

| File | Contents |
|---|---|
| `artifacts/mutants.json` | Full fault inventory with content-derived ids |
| `artifacts/census.json` | Per-fault killed/survived verdict |
| `artifacts/census_summary.json` | The headline numbers above |

### Why you can trust it

Mutant ids are `sha256` over (subject commit, file, function, operator, source
span, replacement), so enumeration order cannot change them. Re-running, or
running on another machine, produces identical ids. Verify with:

```bash
python -m pytest tests -k "deterministic or unique or content_derived"
```

---

## Path B: the full agent comparison

**Runtime: ~3 hours** on the development machine (see the timing note below).

### B1. Install a local model

```bash
# install Ollama from https://ollama.com, then:
ollama pull qwen2.5:7b
```

Placebo talks to Ollama's HTTP API at `http://127.0.0.1:11434`. Confirm it is
reachable:

```bash
python -c "import urllib.request,json; print([m['name'] for m in json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags'))['models']])"
```

The exact model pinned in the results is `qwen2.5:7b`, quantisation `Q4_K_M`,
digest `845dbda0ea48ed74…`, generated at `temperature=0`, `seed=7`,
`num_ctx=8192`.

### B2. Run the pipeline

Requires `artifacts/census.json` from Path A.

```bash
python scripts/run_pipeline.py \
    --conditions baseline_A mutant_aware_B1 placebo_B placebo_C placebo_D \
    --limit 12
```

To reproduce one condition only (about 25–40 minutes each):

```bash
python scripts/run_pipeline.py --conditions baseline_A placebo_D --limit 12
```

### What it does

1. Selects 12 **discovery** faults, stratified round-robin across operator
   families, deterministically.
2. Freezes a stratified **held-out** set of 29 faults: same functions,
   different source spans, same-line siblings excluded, and restricted to
   faults semver's own suite demonstrably kills. The manifest fingerprint is
   `491a2c1f8af0ef27`.
3. Runs each condition's agent over the 12 discovery faults.
4. Assembles each condition's admitted tests into a suite.
5. Applies the same **model-free** green-test repair to every suite: each test is
   run once against correct code and dropped if it fails. A developer would do
   exactly this, so every condition gets it.
6. Writes the raw generation run. The model-free rescore below gives the
   baseline every green candidate, keeps the frozen 29-fault set as the primary
   confirmatory result, and also scores all 80 eligible faults as a transparent
   post-generation robustness analysis with no sampling parameter.

### B3. Assemble and rescore fairly

```bash
python scripts/rescore.py
```

This step makes no model calls. It keeps every baseline candidate that passes
clean code, keeps only oracle-admitted candidates for Placebo conditions, and
refuses to credit any final suite that is red on clean `HEAD`.

### Expected output

A comparison table, plus:

| File | Contents |
|---|---|
| `experiments/results.json` | All per-condition results |
| `benchmark/manifests/split_stratified.json` | Frozen pre-generation confirmatory set (29) |
| `benchmark/manifests/split_primary.json` | Post-generation all-eligible robustness set (80; legacy filename) |
| `experiments/raw/pipeline_*.json` | Every attempt, prompt outcome and admission verdict |
| `artifacts/suites/*.py` | The final test suite each condition produced |
| `trajectories/pipeline_*.jsonl` | Every model call: prompt, system, response, tokens, duration |

### B4. Rebuild the report

Reads only stored artifacts and needs **no model**, so a judge can regenerate
every table without spending a single GPU-second:

```bash
python scripts/build_report.py
```

Writes `artifacts/report.md`.

---

## Path C: close gaps in the real expert suite

The comparison benchmark above uses known-detectable faults so every condition
gets the same 12 paired authoring tasks. This separate product run starts only
from the 6 confirmed faults that actually survived semver's existing suite:

```bash
python scripts/run_real_gap_closure.py
```

It writes `artifacts/suites/real_gap_patch.py`,
`experiments/real_gap_closure.json`, `artifacts/real_gap_report.md`, and a full
agent trajectory. The reported result is the existing 329-test suite plus the
generated patch, not the generated tests in isolation.

---

---

## Path D: the evidence that does not depend on mutation score

Every command below is **deterministic and makes zero model calls**. They are
the answer to "mutation score is only a proxy".

```bash
# Real defects that shipped in semver 3.0.4 and were fixed upstream later.
# Ground truth is the maintainers' own diff and issue number.
python scripts/run_historical_bugs.py          # ~1 s

# The identical pipeline on a second library with a different fault surface.
python scripts/run_multirepo_census.py         # ~4 min

# A level-3 oracle: properties, not recorded output values.
python scripts/run_metamorphic.py              # ~7 s

# Bootstrap spread over stored repeated runs.
python scripts/run_variance.py                 # instant
```

Expected:

| command | expected result |
|---|---|
| `run_historical_bugs.py` | witness for **3/3** behavior-changing bugs; **0/3** detected by semver's own suite; the one behavior-preserving refactor correctly yields no witness |
| `run_multirepo_census.py` | semver **96.2%**, inflection **85.5%** |
| `run_metamorphic.py` | 12/12 properties sound on clean code; detects **1/6** gaps |
| `run_variance.py` | admitted 5/5/5, CI [5.0, 5.0]; retry recoveries 0-2, CI [0.0, 2.0] |

`run_historical_bugs.py` needs a full clone of upstream semver for the fix
commits. Without it the script says so and exits cleanly:

```bash
git clone https://github.com/python-semver/python-semver
```

Adjust `UPSTREAM` at the top of the script to point at that clone.

## Path E: the model-dependent controls

These **do** call the local model and take time.

```bash
# Does the scaffolding help, or does it just buy more model calls?
python scripts/run_equal_budget.py --samples 3 --limit 12    # ~50 min

# Error bars on the headline comparison.
python scripts/run_seeds.py --repeats 3                      # ~2 h
```

Both write incrementally, so a partial run is still usable. Neither is required
to reproduce any headline number; both exist to test whether the headline
numbers survive scrutiny.

## Packaging

```bash
python scripts/package_submission.py
```

Writes `../placebo-submission.zip` and verifies it: under the size limit, every
required deliverable present, no credentials, no workspace or cache files.

## Timing and cost

| Step | Runtime | Cost |
|---|---|---|
| Unit tests | < 1 s | $0 |
| Path A census (185 faults × 329 tests) | 129 s @ 6 workers | $0 |
| Path B, one condition | 25–40 min | $0 |
| Path B, all five conditions | ~3 h | $0 |
| Report rebuild | < 1 s | $0 |

**Total monetary cost: $0.** All inference is local. There is no API key in this
repository, and none is required.

Generation speed measured on the development machine: `qwen2.5:7b` at
**5.8 tok/s** (a 4.7 GB model partially offloaded to a 4 GB GPU). On hardware
that fits the model in VRAM, Path B will be substantially faster.

---

## Determinism: what is and is not reproducible

**Deterministic (should match exactly):**

- the fault inventory and every mutant id;
- the census verdicts and the 96.2% score;
- the frozen confirmatory split and fingerprint `491a2c1f8af0ef27`;
- the deterministic all-eligible robustness set and fingerprint
  `cb088e4cd91a408c` once materialized;
- every admission verdict for a given candidate test, since those are pytest
  runs.

**Not bitwise deterministic:**

- model outputs. Ollama with partial GPU offload does not produce identical
  tokens across runs even at `temperature=0` with a fixed seed; we observed two
  runs of an identical first-attempt prompt diverge. Condition-level numbers in
  the report are **single runs** and will vary by a case or two.

This is disclosed rather than hidden: Path A, which carries the project's
central claim, involves no model and is fully reproducible.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'semver'`**: the subject is vendored at
`subject/semver`; the runner sets `PYTHONPATH` to its workspace copy. Do not
`pip install semver`; an installed copy can shadow the vendored one. Remove it
with `python -m pip uninstall semver`.

**Census reports the baseline suite is not green**: the runner refuses to score
faults when the clean suite is red, by design. Check `python -m pytest
subject/tests` with `PYTHONPATH=subject`.

**Windows: `FileExistsError` on the workspace**: handled by a retrying
force-remove in `SubjectRunner.prepare()`. If it persists, delete
`.placebo-ws/` manually.

**Model unreachable**: Path A does not need the model. Run it first to confirm
the core result, then debug Ollama separately.

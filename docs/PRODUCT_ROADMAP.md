# Placebo after the hackathon — product and research roadmap

This is deliberately prioritized. It is not a list of every feature that might
look impressive. The project should not claim to be a general test auditor until
the Phase 1 exit criteria are met.

## Current state

Placebo is a strong, evidence-backed research prototype for Python/pytest. It
already has:

- a deterministic Python AST mutation engine with content-addressed fault ids;
- clean/fault two-sided admission and static anti-cheating gates;
- sealed held-out evaluation and an equal-compute baseline;
- per-test marginal value, sibling redundancy, and set-cover minimization;
- executable evidence bundles and consistency checks;
- deterministic counterexample search for a semver-specific input domain;
- twelve semver metamorphic properties;
- results on two repositories, three behavior-changing historical semver bugs,
  one behavior-preserving refactor, and three repeated model runs; and
- a prepared but unrun blinded reviewer study.

The core weakness is now product truth: `placebo audit` looks generic, but the
CLI, oracle DSL, counterexample domains, evidence builder, and subject layout are
still hardcoded around the vendored semver repository. The second repository
shows that the mutation engine transfers; it does not show that the full audit
workflow transfers.

## Phase 1 — make the command honest and useful

### 1. Repository adapter and preflight

Add a versioned `.placebo.yml` contract:

```yaml
version: 1
language: python
test_framework: pytest
test_command: [python, -m, pytest, -q]
source_roots: [src]
test_roots: [tests]
mutation_targets: [src/**/*.py]
timeout_seconds: 60
container:
  image: python:3.13-slim
  network: none
```

Add these commands:

```text
placebo doctor <repo>             validate support without changing anything
placebo census <repo>             create/cache the existing-suite fault map
placebo audit-pr <repo> <diff>    audit only tests added or changed by a diff
placebo verify <bundle>           replay without model access
```

Remove `SUBJECT_COMMIT`, `TARGET_FILES`, `semver` imports, and repository paths
from generic modules. Put subject-specific expression domains and properties in
adapters/plugins. Unsupported repositories must fail with an actionable reason,
not a traceback.

**Exit criterion:** clone three pinned public Python repositories into clean
directories and run `doctor -> census -> audit-pr -> verify` without editing
Placebo source code. One should use a `src/` layout, one a flat package, and one
a monorepo/subpackage layout.

### 2. Make PR audits fast enough to use

The measured public 33-test/185-fault audit took about twelve minutes on the
development machine and was previously silent until completion. Progress is now
streamed, but speed still blocks adoption.

Build:

- a persistent result cache keyed by subject commit, environment fingerprint,
  mutant id, patch hash, and pytest node id;
- coverage-based test selection so a mutant runs only tests that execute its
  source span, with a conservative full-suite fallback;
- changed-file and changed-function mutation scope for pull requests;
- parallel workers with bounded CPU and memory;
- checkpoint/resume after interruption; and
- a time budget that returns partial evidence with explicit coverage of the
  evaluated fault corpus.

**Exit criterion:** after one cached census, audit a typical 5–20-test PR in
under two minutes locally; a no-change rerun in under ten seconds; never lose a
kill found by the exhaustive reference run on the benchmark repositories.

### 3. Harden execution

Disposable directory copies are not a security boundary. Run repository setup,
tests, model-produced code, and oracle probes inside a networkless container
with read-only inputs, a writable scratch mount, CPU/memory/process/time limits,
and no host credentials. Record the image digest in the evidence bundle.

**Exit criterion:** adversarial tests attempting filesystem escape, network
access, process spawning, environment-secret reads, and resource exhaustion are
blocked and covered by integration tests on Linux CI.

## Phase 2 — solve the oracle problem instead of hiding it

Every proposed test should carry an explicit oracle level:

1. specification/example/invariant;
2. independent implementation or stable previous release agreement;
3. metamorphic relation;
4. current-implementation snapshot.

Level 4 must never be presented as semantic correctness. Add policy controls so
teams can reject brittle snapshot categories such as exact exception text,
timestamps, ordering, repr output, and unstable serialization. Let a human
approve or rewrite the intended contract before export.

Add automatic candidate sources for levels 1–3:

- extract examples and invariants from docs, type contracts, schemas, and issue
  acceptance criteria, retaining source citations;
- differential checks against previous releases or independent libraries;
- property-based generation and shrinking for declared types/domains; and
- an abstention path when no trustworthy oracle exists.

**Exit criterion:** on a labeled set of historical bugs, report separately how
often Placebo finds a witness and how often the produced assertion agrees with
the maintainer's fixed behavior. Measure false behavior-locking, not only kills.

## Phase 3 — establish external validity

The current historical result is promising but too small: three
behavior-changing bugs from one library. Build a frozen benchmark of at least
50 historical bugs across 8–10 projects using a reproducible source such as
Tests4Py or a legally reviewed BugsInPy/BugsInPy++ workflow.

Prevent leakage:

- freeze buggy/fixed commits and manifests before prompt or domain tuning;
- hide the fixed patch and bug-triggering test from generation;
- tune on projects disjoint from final evaluation projects;
- report setup failures and unsupported cases in the denominator; and
- publish every witness, timeout, abstention, and false lock.

Use stronger baselines:

- a current frontier coding model with repository context;
- equal-token and equal-wall-time best-of-N prompting;
- property-based/search-based test generation where applicable; and
- established mutation-guided generation systems when reproducible.

Run at least five independent repetitions for stochastic conditions. Report
paired per-fault differences, bootstrap intervals, wall time, model tokens, and
cost. Do not use a zero-retained small-model baseline as the primary comparison.

**Exit criterion:** material improvement over the strongest equal-budget
baseline on held-out projects and historical bugs, with uncertainty intervals
and a predeclared primary metric.

## Phase 4 — validate the human value proposition

The reviewer-study instrument exists but has no participants. Run it blinded
with at least 12 experienced engineers. Compare normal test PR review with a
Placebo report on:

- time to decision;
- correct keep/remove decisions against an adjudicated rubric;
- false rejection of requirement-carrying tests;
- confidence calibration;
- usefulness of fault witnesses; and
- trust after seeing uncertainty and oracle-level labels.

The study must allow “cannot decide from this evidence.” Record disagreements
and qualitative failure cases. The goal is not a flattering satisfaction score;
it is evidence that the audit improves decisions without automating judgment.

**Exit criterion:** reviewers make more accurate decisions or reach equally
accurate decisions materially faster, without increased false removals.

## Phase 5 — ship the workflow teams will actually adopt

Build a GitHub App/Action that comments only on changed tests and exposes:

- concise per-test verdicts with exact counterexamples;
- the existing-suite and sibling marginal kill matrix;
- the minimized patch as a suggestion, never an automatic merge;
- oracle level and brittleness warnings;
- evaluated/unevaluated fault scope and cache status;
- links to raw logs and a downloadable replay bundle; and
- SARIF/check annotations for machine integration.

Add a local HTML report that works for any adapter rather than reading fixed
semver artifacts. Track results over time so teams can detect decision decay:
tests that once carried unique value but became redundant after later changes.

**Exit criterion:** install on a real public repository, audit pull requests for
four weeks, and publish the failures and operating cost.

## Engineering quality gate

The current unit suite passes but line coverage is about 46 percent, with the
CLI, evidence bundle builder, census runner, counterexample search, and
metamorphic engine containing major untested paths. Before a 1.0 release:

- reach at least 85 percent branch coverage on generic core modules;
- add end-to-end tests for every public CLI command;
- test interruption, timeout, malformed configuration, cache corruption, and
  cross-platform path handling;
- run Linux, Windows, and macOS CI for generic logic;
- add schema validation and migration tests for configs, manifests, and bundles;
- benchmark false positives and performance regressions in CI; and
- publish a stable plugin API and semantic-versioning policy.

Coverage is not the goal by itself—the project already argues that—but public
paths with zero automated execution are an avoidable reliability risk.

## What not to build yet

- another conversational agent or critic;
- a VS Code time-travel UI;
- support for six languages before Python works generically;
- automatic merging or autonomous deletion of tests;
- more semver-specific mutation operators or hand-built input literals;
- a polished dashboard that still reads committed experiment JSON; or
- claims of correctness, “proof-carrying” patches, or universal test quality.

## The defensible destination

> Placebo is a repository-independent admission and accounting layer for
> machine-generated tests. It measures each test's marginal fault sensitivity,
> labels the strength of its oracle, minimizes redundant review work, and ships
> replayable evidence while leaving semantic acceptance to a human.

That is narrower than “AI that writes perfect tests,” and much more credible.

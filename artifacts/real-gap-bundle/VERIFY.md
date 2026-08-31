# Verifying this bundle

Every claim in `evidence/` is an executable statement. Nothing here asks you to
trust the agent that produced it.

## What is claimed

For each test in `patch/`, Placebo claims exactly two things:

1. it **passes** against the unmodified subject at commit `6adf8765f6e2`;
2. it **fails** when one specific, named fault is injected.

Both were verified by running pytest before the test was admitted. The fault
each test detects is recorded in `evidence/tests.json`, including the exact
one-line source diff.

## Re-check it yourself

```bash
python scripts/verify_bundle.py --bundle real-gap-bundle
```

This re-applies each recorded fault and re-runs the corresponding test. It
reports `HOLDS` or `BROKEN` per test and exits non-zero if any claim fails.

## What is NOT claimed

- **Not** that the subject is bug-free. Placebo detects injected faults, not
  unknown real ones.
- **Not** that these tests are sufficient. They close specific measured gaps.
- **Not** that mutation score equals real-fault detection. It is a proxy; see
  `LIMITATIONS` in the project README.
- **Not** that this should be merged automatically. It is a proposal for a
  qualified human reviewer.

## Evaluation result

The suite's aggregate evaluation is in `evidence/heldout.json`. For benchmark
bundles this is the held-out score described by the repository's split
manifests; for real-gap bundles it is closure on manually confirmed repository
gaps. The per-test claims above remain independently replayable evidence in
either case.

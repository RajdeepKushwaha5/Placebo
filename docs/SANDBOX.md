# Execution isolation

Placebo runs two kinds of code it did not write.

Repository tests do whatever their authors made them do: open sockets, spawn
processes, read anything the invoking user can read. Model-produced tests are
worse, because nobody wrote them and they arrive from a provider Placebo does
not control.

Until this existed, both ran on the host as the invoking user, with that user's
environment, that user's credentials in it, that user's home directory readable
and the network up. A disposable directory copy protected the *source* and
nothing else. `LIMITATIONS.md` said so; this is the fix.

## Setup

```bash
docker build -t placebo-runner:1 .
```

That is the whole setup. The image carries the pinned test runner and nothing
else: no compilers, no package manager credentials, no network tooling. It is
built from `python:3.13-slim` with `pytest`, `pytest-cov` and `coverage` at the
same versions as `requirements.lock`, so a result produced inside the container
and one produced on the host are comparable.

Placebo then uses it automatically:

```bash
placebo audit patch.py                   # isolated if the image is built
placebo audit patch.py --sandbox docker  # isolated, or refuse
placebo audit patch.py --unsafe-local    # on this host, no boundary
```

## What the boundary provides

| property | how |
|---|---|
| no network | `--network none` |
| source cannot be written | subject mounted read-only at `/subject` |
| only the workspace is writable | one bind mount at `/work`, already a throwaway copy |
| no credentials | the environment is built from an allowlist, never inherited |
| no privileges | `--cap-drop ALL`, `no-new-privileges`, non-root user |
| immutable root | `--read-only`, with a `noexec,nosuid` tmpfs for scratch |
| bounded cpu and memory | `--cpus`, `--memory`, and `--memory-swap` set equal so swap is not an escape |
| bounded processes | `--pids-limit` |
| bounded time | the container's limit, plus a host timeout as a backstop |
| pinned image | recorded by digest in the evidence bundle |

Each of those is asserted by a test named after it, so a refactor that drops
`--network none` fails a test about the network rather than a vague one about
arguments. Eleven further tests are adversarial: they start real containers and
attempt the escape, then assert it did not work.

```bash
python -m pytest tests/test_sandbox.py
```

Without a reachable Docker daemon the adversarial tests skip rather than pass,
because a test that silently exercises nothing is worse than one that says it
did not run.

## Cost

Measured on the development machine: about **0.4 seconds** per execution over
local, roughly **1.3 minutes** across a 185-fault audit. Results are cached, so
a repeat audit pays it once rather than per run. Isolation did not have to be
traded against usability.

## The fallback is explicit

Local execution stays available, because Docker is not always present, but it
is never silently substituted:

* `--sandbox docker` refuses rather than degrading. A run asked to be isolated
  that quietly was not would put a false claim in its evidence bundle.
* `--sandbox auto`, the default, prefers the container and falls back to the
  host while saying so on stdout.
* `--unsafe-local` is spelled that way because the flag should say what it
  costs.

Whichever ran is recorded in the evidence bundle and in SARIF output, so a
reader can tell an isolated result from a host one afterwards rather than only
at the moment of running.

## What this does not claim

A container is a strong boundary, not a perfect one. Kernel escapes exist, and
a determined attacker with a kernel bug is outside what this addresses. The
threat being handled is the realistic one: test code that reads a token out of
the environment, writes outside its workspace, calls home, or exhausts the
machine.

Nor does it defend against a subject whose *own* test suite is malicious toward
its own repository. Placebo mutates a copy, so the original is safe, but a
suite that deletes its own working directory will succeed in deleting the copy.

## A failure worth naming

The first containerised audit reported all 33 tests as `HARMFUL`. The image had
no pytest, so nothing could execute, and "red against correct code" and "the
harness could not run anything" produce the same observation.

Placebo now runs the subject's own suite before trusting any verdict, and
refuses with an actionable message when it cannot pass. The census already did
this; the audit did not, and the audit is the path where a wrong answer would
have been believed.

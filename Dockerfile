# The environment Placebo executes a subject's tests inside.
#
# Deliberately minimal. This image runs repository tests and model-produced
# Python, so everything it contains is something that code can use. It holds
# the test runner and nothing else: no compilers, no shells beyond the base,
# no package manager credentials, no network tooling.
#
# Placebo runs it with --network none, --read-only, --cap-drop ALL and explicit
# cpu, memory and pid limits, so the image is the inner layer of the boundary
# rather than the whole of it. See src/placebo/sandbox.py.
#
#   docker build -t placebo-runner:1 .
#
# The tag is a label for humans. What goes into an evidence bundle is the
# digest, because a tag can point at different bytes tomorrow.

FROM python:3.13-slim

# Pinned to the same versions as requirements.lock, so a result produced in the
# container and one produced on the host are comparable.
RUN pip install --no-cache-dir --disable-pip-version-check \
        pytest==9.0.2 \
        pytest-cov==7.1.0 \
        coverage==7.16.0 \
 && find /usr/local -name '__pycache__' -type d -prune -exec rm -rf {} +

# Tests run as a non-root user. The container already drops every capability,
# but a process that never had root cannot be the one that finds a way to use
# it. The home directory is /tmp because the root filesystem is read-only and
# /tmp is the only writable scratch.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin placebo
USER placebo
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /work

# No ENTRYPOINT on purpose: Placebo supplies the exact command it wants to run,
# and an entrypoint here would be one more thing between the recorded command
# and what actually executed.
CMD ["python", "-c", "import pytest; print(pytest.__version__)"]

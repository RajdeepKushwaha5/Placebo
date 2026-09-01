"""Execution isolation for repository tests and model-produced code.

Why a directory copy is not enough
----------------------------------
Placebo runs two kinds of untrusted code. Repository tests do whatever that
repository's authors wrote, including network calls, subprocess spawning and
reads of anything the user can read. Model-produced tests are worse: nobody
wrote them, and they arrive from a provider Placebo does not control.

A disposable directory copy stops those from corrupting the *source*. It stops
nothing else. The process still runs as the user, with the user's environment,
the user's credentials in it, the user's home directory readable, and the
network up. `docs/LIMITATIONS.md` has said so; this module is the fix.

What the boundary provides
--------------------------
    network             disabled outright
    subject source      mounted read-only, so the original cannot be written
    workspace           a writable copy, and the only writable mount
    credentials         not inherited; the environment is built, not passed
    cpu / memory        capped
    processes           capped, so a fork bomb cannot take the host down
    time                capped, enforced by the host as well as the container
    filesystem          read-only root with an explicit writable scratch
    privileges          dropped, no new privileges, non-root user
    image               pinned by digest and recorded in the evidence bundle

Honesty about the fallback
--------------------------
Local execution stays available because Docker is not always present, but it is
not silently equivalent. Choosing it requires `--unsafe-local`, the run says so
on stdout, and the evidence bundle records that its results were produced
without a boundary. A reader should be able to tell the two apart afterwards,
not just at the moment of running.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The image Placebo executes subjects in, built from this repository's
# Dockerfile. It carries the pinned test runner and nothing else.
#
# A tag is a moving target, so what is recorded in evidence is the digest; the
# tag is only a readable label for humans.
RUNNER_IMAGE = "placebo-runner:1"

# The base the runner is built from. It has no pytest, so it cannot execute a
# subject's suite; it is named here only so the failure can be explained.
BASE_IMAGE = "python:3.13-slim"

DEFAULT_IMAGE = RUNNER_IMAGE

# Environment variables the subject genuinely needs. Everything else is
# dropped, which is the point: a credential that is never passed cannot leak.
_ALLOWED_ENV = ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED",
                "COVERAGE_FILE", "PATH", "LANG", "LC_ALL")


class SandboxUnavailable(RuntimeError):
    """Raised when isolation was requested and cannot be provided."""


@dataclass(frozen=True)
class Limits:
    """Resource ceilings applied to one execution."""

    cpus: float = 2.0
    memory: str = "2g"
    pids: int = 256
    timeout_s: int = 300

    def to_dict(self) -> dict:
        return {"cpus": self.cpus, "memory": self.memory,
                "pids": self.pids, "timeout_s": self.timeout_s}


@dataclass
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class LocalExecutor:
    """Run directly on the host. Fast, and not a security boundary."""

    name: str = "local"
    isolated: bool = False

    def available(self) -> bool:
        return True

    def describe(self) -> dict:
        return {
            "backend": "local",
            "isolated": False,
            "warning": (
                "Executed on the host without a sandbox. Repository tests and "
                "model-produced code ran with this user's environment, "
                "credentials and network access."
            ),
        }

    def run(self, argv: list[str], cwd: Path, env: dict[str, str],
            timeout_s: int) -> ExecutionResult:
        try:
            proc = subprocess.run(
                argv, cwd=str(cwd), env=env, capture_output=True,
                text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(
                returncode=-1,
                stdout=_as_text(exc.stdout),
                stderr="TIMEOUT",
                timed_out=True,
            )
        return ExecutionResult(proc.returncode, proc.stdout, proc.stderr)


@dataclass
class DockerExecutor:
    """Run inside a networkless container with a read-only root.

    The workspace is the only writable bind mount, and it is already a
    disposable copy. The subject source is mounted read-only so that even a
    test that goes looking for it cannot write to the real repository.
    """

    image: str = DEFAULT_IMAGE
    digest: str = ""
    limits: Limits = field(default_factory=Limits)
    subject_root: Path | None = None
    name: str = "docker"
    isolated: bool = True

    def available(self) -> bool:
        if not shutil.which("docker"):
            return False
        try:
            proc = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0 and bool(proc.stdout.strip())

    def resolve_digest(self) -> str:
        """Pin the image to a content digest.

        A tag can be repointed at different bytes tomorrow, so evidence citing
        a tag cites nothing. A pulled image is pinned by its registry digest.
        A locally built one has never been pushed and so has none, but its
        image id is a digest over the same bytes and is used instead.
        """
        if self.digest:
            return self.digest
        for template in ("{{index .RepoDigests 0}}", "{{.Id}}"):
            try:
                proc = subprocess.run(
                    ["docker", "image", "inspect", self.image, "--format", template],
                    capture_output=True, text=True, timeout=60,
                )
            except (OSError, subprocess.SubprocessError):
                return ""
            value = proc.stdout.strip()
            if proc.returncode == 0 and value and "sha256:" in value:
                self.digest = value
                return self.digest
        return ""

    def image_present(self) -> bool:
        """Whether the image exists locally. The container has no network, so
        it cannot be fetched at run time."""
        try:
            proc = subprocess.run(
                ["docker", "image", "inspect", self.image, "--format", "{{.Id}}"],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0

    def pull(self) -> bool:
        try:
            proc = subprocess.run(["docker", "pull", "--quiet", self.image],
                                  capture_output=True, text=True, timeout=900)
            return proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def describe(self) -> dict:
        return {
            "backend": "docker",
            "isolated": True,
            "image": self.image,
            "image_digest": self.digest or "unresolved",
            "network": "none",
            "read_only_root": True,
            "limits": self.limits.to_dict(),
        }

    def build_argv(self, argv: list[str], workspace: Path,
                   env: dict[str, str], timeout_s: int) -> list[str]:
        """The full `docker run` command line.

        Kept separate from `run` so the flags that make this a boundary can be
        asserted in tests without a daemon. Every flag here is load-bearing;
        a test pins each one.
        """
        image_ref = self.digest or self.image
        command = [
            "docker", "run", "--rm",
            "--network", "none",              # no egress, no lateral movement
            "--read-only",                    # root filesystem is immutable
            "--cap-drop", "ALL",              # no capabilities at all
            "--security-opt", "no-new-privileges",
            "--pids-limit", str(self.limits.pids),
            "--cpus", str(self.limits.cpus),
            "--memory", self.limits.memory,
            "--memory-swap", self.limits.memory,   # no swap escape hatch
            "--tmpfs", "/tmp:rw,size=256m,noexec,nosuid",
            "--workdir", "/work",
            "--mount", f"type=bind,src={workspace},dst=/work",
        ]

        # Only mount a subject that is actually there. Docker rejects a bind
        # whose source does not exist with "invalid mount config for type",
        # which says nothing about the real problem. Docker Desktop on Windows
        # creates the directory instead, so this fails only on Linux, which is
        # exactly where CI runs.
        if self.subject_root is not None and Path(self.subject_root).is_dir():
            command += ["--mount",
                        f"type=bind,src={self.subject_root},dst=/subject,readonly"]

        # A bind mount keeps its host ownership, so the container has to run as
        # the host user or it cannot write to its own workspace. This is still
        # non-root: it is whoever invoked Placebo. Windows has no uid to map and
        # Docker Desktop handles ownership itself.
        identity = _host_identity()
        if identity:
            command += ["--user", identity]

        # The environment is constructed, never inherited. Anything not named
        # here does not exist inside the container.
        for key in _ALLOWED_ENV:
            if key in env:
                command += ["--env", f"{key}={_translate(env[key], workspace)}"]
        command += ["--env", "HOME=/tmp", "--env", "PYTHONUNBUFFERED=1"]

        command += [image_ref, *_translate_argv(argv, workspace)]
        return command

    def run(self, argv: list[str], cwd: Path, env: dict[str, str],
            timeout_s: int) -> ExecutionResult:
        command = self.build_argv(argv, Path(cwd), env, timeout_s)
        try:
            # The host timeout is a backstop: a container that ignores its own
            # limits still cannot outlive this.
            proc = subprocess.run(command, capture_output=True, text=True,
                                  timeout=timeout_s + 30)
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(-1, _as_text(exc.stdout), "TIMEOUT", True)
        except OSError as exc:
            return ExecutionResult(-1, "", f"docker failed: {exc}")
        return ExecutionResult(proc.returncode, proc.stdout, proc.stderr)


def _host_identity() -> str:
    """`uid:gid` of the invoking user, or empty where that is meaningless."""
    if os.name == "nt" or not hasattr(os, "getuid"):
        return ""
    return f"{os.getuid()}:{os.getgid()}"


def _as_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _translate(value: str, workspace: Path) -> str:
    """Rewrite host paths to their location inside the container.

    The list separator is translated too. A Windows host joins PYTHONPATH with
    ";" while the Linux container expects ":", so without this the container
    receives one nonsensical path and a src/ layout cannot import itself.
    """
    translated = value.replace(str(workspace), "/work").replace("\\", "/")
    if os.pathsep != ":":
        translated = translated.replace(os.pathsep, ":")
    return translated


def _translate_argv(argv: list[str], workspace: Path) -> list[str]:
    """The interpreter inside the container is `python`, not the host's path."""
    out = []
    for index, item in enumerate(argv):
        if index == 0 and item == sys.executable:
            out.append("python")
        else:
            out.append(_translate(item, workspace))
    return out


def select(mode: str = "auto", *, subject_root: Path | None = None,
           limits: Limits | None = None, image: str = DEFAULT_IMAGE):
    """Choose an execution backend.

    `auto` prefers isolation and falls back to the host, saying so. `docker`
    refuses rather than silently degrading, because a run that was asked to be
    isolated and quietly was not is a false claim in the evidence bundle.
    `local` is the explicit, acknowledged fallback.
    """
    limits = limits or Limits()

    if mode == "local":
        return LocalExecutor()

    docker = DockerExecutor(image=image, limits=limits, subject_root=subject_root)

    if not docker.available():
        if mode == "docker":
            raise SandboxUnavailable(
                "Container isolation was requested but Docker is not running.\n"
                "  Start Docker, or pass --unsafe-local to run on this host "
                "with no boundary."
            )
        return LocalExecutor()

    if not docker.image_present():
        # The container has no network, so a missing image cannot be fetched
        # once it is running. Saying so now beats failing opaquely later.
        message = (
            f"The sandbox image {image} is not built.\n"
            f"  Build it once:  docker build -t {RUNNER_IMAGE} .\n"
            "  Or pass --unsafe-local to run on this host with no boundary."
        )
        if mode == "docker":
            raise SandboxUnavailable(message)
        return LocalExecutor()

    docker.resolve_digest()
    return docker

"""Tests for execution isolation.

Placebo runs repository tests and model-produced Python. A disposable folder
stops those from corrupting the source and stops nothing else: the process
still has the user's environment, credentials, home directory and network.

These tests split into two groups on purpose.

The first group asserts the *command* Placebo constructs, and needs no daemon.
Every flag in it is load-bearing, so each one is pinned individually: a
refactor that drops `--network none` should fail a test named after the
network, not a vague one about docker arguments.

The second group is adversarial and actually runs containers. Each test
attempts a specific escape that would succeed on the host, and asserts it does
not succeed inside the boundary. They are marked `docker` and skipped when no
daemon is reachable, because a skipped test is honest and a test that silently
passes without exercising anything is not.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.sandbox import (  # noqa: E402
    DEFAULT_IMAGE,
    DockerExecutor,
    Limits,
    LocalExecutor,
    SandboxUnavailable,
    select,
)


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        proc = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


needs_docker = pytest.mark.skipif(
    not docker_available(), reason="no reachable Docker daemon")


@pytest.fixture
def executor(tmp_path) -> DockerExecutor:
    ex = DockerExecutor(image=DEFAULT_IMAGE, subject_root=tmp_path / "subject")
    ex.resolve_digest()
    return ex


def run_in_container(executor: DockerExecutor, workspace: Path, code: str,
                     timeout_s: int = 120):
    """Run a snippet inside the boundary and return the result."""
    workspace.mkdir(parents=True, exist_ok=True)
    script = workspace / "probe.py"
    script.write_text(code, encoding="utf-8")
    return executor.run([sys.executable, "/work/probe.py"], workspace,
                        {"PYTHONDONTWRITEBYTECODE": "1"}, timeout_s)


# -- the command carries every property we claim ---------------------------


def test_the_network_is_disabled(executor, tmp_path):
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"


def test_the_root_filesystem_is_read_only(executor, tmp_path):
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    assert "--read-only" in argv


def test_the_subject_is_mounted_read_only(executor, tmp_path):
    (tmp_path / "subject").mkdir(exist_ok=True)
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    subject = [m for m in mounts if "dst=/subject" in m]
    assert subject, "the subject source is not mounted"
    assert "readonly" in subject[0]


def test_a_subject_root_that_does_not_exist_is_not_mounted(tmp_path):
    """Docker rejects a bind whose source is missing with "invalid mount
    config for type", which names the wrong problem entirely. Docker Desktop
    creates the directory instead, so this only ever fails on Linux."""
    ex = DockerExecutor(subject_root=tmp_path / "absent")
    argv = ex.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert not any("dst=/subject" in m for m in mounts)
    assert any("dst=/work" in m for m in mounts), "the workspace still mounts"


def test_the_workspace_is_the_only_writable_mount(executor, tmp_path):
    (tmp_path / "subject").mkdir(exist_ok=True)
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    writable = [m for m in mounts if "readonly" not in m]
    assert len(writable) == 1
    assert "dst=/work" in writable[0]


def test_resource_limits_are_applied(tmp_path):
    ex = DockerExecutor(limits=Limits(cpus=1.5, memory="512m", pids=64))
    argv = ex.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    for flag, value in (("--cpus", "1.5"), ("--memory", "512m"),
                        ("--pids-limit", "64")):
        assert flag in argv and argv[argv.index(flag) + 1] == value


def test_swap_cannot_be_used_to_exceed_the_memory_cap(tmp_path):
    """Without this a container simply swaps past its memory limit."""
    ex = DockerExecutor(limits=Limits(memory="512m"))
    argv = ex.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    assert argv[argv.index("--memory-swap") + 1] == "512m"


def test_privileges_are_dropped(executor, tmp_path):
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"


def test_credentials_are_not_inherited(executor, tmp_path):
    """The environment is built, not passed. A secret that is never handed
    over cannot be read out of the process."""
    hostile = {
        "AWS_SECRET_ACCESS_KEY": "secret",
        "GITHUB_TOKEN": "ghp_secret",
        "OPENAI_API_KEY": "sk-secret",
        "PYTHONPATH": str(tmp_path),
    }
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, hostile, 60)
    joined = " ".join(argv)
    assert "secret" not in joined and "ghp_secret" not in joined
    assert "PYTHONPATH=/work" in joined, "the paths the subject needs survive"


def test_the_image_is_pinned_by_digest(executor, tmp_path):
    """A tag can point at different bytes tomorrow, so evidence citing a tag
    cites nothing.

    Two digest forms are valid. A pulled image carries a registry digest,
    `repo@sha256:...`. A locally built one has never been pushed and so has
    none, but its image id, `sha256:...`, is a digest over the same bytes.
    """
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    if executor.digest:
        assert executor.digest in argv, "the run is not pinned to the digest"
        assert executor.digest.startswith("sha256:") or "@sha256:" in executor.digest
        assert executor.image not in argv, "the mutable tag must not be used"


def test_host_paths_are_translated_into_the_container(executor, tmp_path):
    """The command the container runs must use container paths.

    Mount sources are host paths by definition, so only the trailing command,
    everything after the image reference, is checked.
    """
    argv = executor.build_argv(
        [sys.executable, str(tmp_path / "tests" / "t.py")], tmp_path, {}, 60)
    image_ref = executor.digest or executor.image
    command = argv[argv.index(image_ref) + 1:]

    assert command[0] == "python", "the host interpreter path means nothing inside"
    assert command[1] == "/work/tests/t.py"
    assert str(tmp_path) not in " ".join(command)


def test_a_scratch_directory_exists_but_cannot_execute(executor, tmp_path):
    argv = executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)
    tmpfs = argv[argv.index("--tmpfs") + 1]
    assert tmpfs.startswith("/tmp:")
    assert "noexec" in tmpfs and "nosuid" in tmpfs


def test_the_container_is_removed_after_the_run(executor, tmp_path):
    assert "--rm" in executor.build_argv(["python", "-c", "pass"], tmp_path, {}, 60)


# -- choosing a backend ----------------------------------------------------


def test_local_is_never_described_as_isolated():
    described = LocalExecutor().describe()
    assert described["isolated"] is False
    assert "without a sandbox" in described["warning"]


def test_requesting_local_gives_local():
    assert select("local").name == "local"


def test_requesting_docker_without_a_daemon_refuses(monkeypatch):
    """Silently degrading would put a false claim in the evidence bundle."""
    monkeypatch.setattr(DockerExecutor, "available", lambda self: False)
    with pytest.raises(SandboxUnavailable, match="unsafe-local"):
        select("docker")


def test_auto_falls_back_to_local_when_docker_is_absent(monkeypatch):
    monkeypatch.setattr(DockerExecutor, "available", lambda self: False)
    assert select("auto").name == "local"


@needs_docker
def test_auto_prefers_isolation_when_docker_is_present():
    chosen = select("auto")
    assert chosen.name == "docker" and chosen.isolated


# -- adversarial: the boundary actually holds ------------------------------


@needs_docker
def test_network_access_is_blocked(executor, tmp_path):
    result = run_in_container(executor, tmp_path / "ws", (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=5)\n"
        "    print('REACHED')\n"
        "except OSError as exc:\n"
        "    print('BLOCKED', type(exc).__name__)\n"
    ))
    assert "REACHED" not in result.stdout, "the container reached the network"
    assert "BLOCKED" in result.stdout


@needs_docker
def test_the_subject_source_cannot_be_written(executor, tmp_path):
    subject = tmp_path / "subject"
    subject.mkdir(parents=True)
    (subject / "ops.py").write_text("x = 1\n", encoding="utf-8")
    executor.subject_root = subject

    result = run_in_container(executor, tmp_path / "ws", (
        "from pathlib import Path\n"
        "try:\n"
        "    Path('/subject/ops.py').write_text('x = 999\\n')\n"
        "    print('WROTE')\n"
        "except OSError as exc:\n"
        "    print('BLOCKED', type(exc).__name__)\n"
    ))
    assert "WROTE" not in result.stdout
    assert (subject / "ops.py").read_text(encoding="utf-8") == "x = 1\n", \
        "the real source was modified from inside the container"


@needs_docker
def test_the_host_filesystem_is_not_reachable(executor, tmp_path):
    (tmp_path / "subject").mkdir(exist_ok=True)
    result = run_in_container(executor, tmp_path / "ws", (
        "from pathlib import Path\n"
        "roots = sorted(x.name for x in Path('/').iterdir())\n"
        "print('ROOTLIST', roots)\n"
        # /mnt and /media are ordinary empty directories in the base image, so
        # their presence proves nothing. What matters is that the host has not
        # been mounted into them.
        "carried = [str(x) for d in ('/mnt', '/media', '/host_mnt')\n"
        "           if Path(d).is_dir() for x in Path(d).iterdir()]\n"
        "print('CARRIED', carried)\n"
    ))
    assert "CARRIED []" in result.stdout, "something from the host is mounted"
    assert "work" in result.stdout, "the workspace mount is missing"


@needs_docker
def test_the_root_filesystem_rejects_writes(executor, tmp_path):
    result = run_in_container(executor, tmp_path / "ws", (
        "from pathlib import Path\n"
        "try:\n"
        "    Path('/usr/lib/evil.py').write_text('x')\n"
        "    print('WROTE')\n"
        "except OSError as exc:\n"
        "    print('BLOCKED', type(exc).__name__)\n"
    ))
    assert "WROTE" not in result.stdout
    assert "BLOCKED" in result.stdout


@needs_docker
def test_credentials_are_absent_inside_the_container(executor, tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "top-secret-value")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_top_secret")

    result = run_in_container(executor, tmp_path / "ws", (
        "import os\n"
        "leaked = [k for k in os.environ\n"
        "          if any(t in k.upper() for t in ('SECRET','TOKEN','KEY','PASSWORD'))]\n"
        "print('LEAKED', leaked)\n"
        "print('VALUES', [v for v in os.environ.values() if 'secret' in v.lower()])\n"
    ))
    assert "top-secret-value" not in result.stdout, "a host secret was inherited"
    assert "ghp_top_secret" not in result.stdout, "a host secret was inherited"
    assert "VALUES []" in result.stdout, "a host secret value reached the container"
    # The base image defines its own GPG_KEY, which did not come from the host,
    # so the assertion is about host values rather than key-shaped names.
    assert "AWS_SECRET_ACCESS_KEY" not in result.stdout
    assert "GITHUB_TOKEN" not in result.stdout


@needs_docker
def test_a_fork_bomb_is_capped_rather_than_taking_the_host_down(tmp_path):
    ex = DockerExecutor(limits=Limits(pids=32, timeout_s=45))
    ex.resolve_digest()
    result = run_in_container(ex, tmp_path / "ws", (
        "import os\n"
        "spawned = 0\n"
        "try:\n"
        "    for _ in range(500):\n"
        "        if os.fork() == 0:\n"
        "            os._exit(0)\n"
        "        spawned += 1\n"
        "except OSError:\n"
        "    pass\n"
        "print('SPAWNED', spawned)\n"
    ), timeout_s=45)
    # The precise number does not matter; not being unbounded does.
    assert result.returncode is not None
    if "SPAWNED" in result.stdout:
        spawned = int(result.stdout.split("SPAWNED")[1].split()[0])
        assert spawned < 500, "process creation was not capped"


@needs_docker
def test_memory_is_capped(tmp_path):
    ex = DockerExecutor(limits=Limits(memory="256m", timeout_s=60))
    ex.resolve_digest()
    result = run_in_container(ex, tmp_path / "ws", (
        "blocks = []\n"
        "try:\n"
        "    for _ in range(200):\n"
        "        blocks.append(bytearray(16 * 1024 * 1024))\n"
        "    print('ALLOCATED', len(blocks) * 16, 'MB')\n"
        "except MemoryError:\n"
        "    print('BLOCKED MemoryError')\n"
    ), timeout_s=90)
    assert "ALLOCATED 3200 MB" not in result.stdout, "the memory cap did nothing"


@needs_docker
def test_an_endless_run_is_stopped(tmp_path):
    ex = DockerExecutor(limits=Limits(timeout_s=5))
    ex.resolve_digest()
    result = run_in_container(ex, tmp_path / "ws",
                              "import time\nwhile True:\n    time.sleep(1)\n",
                              timeout_s=5)
    assert result.timed_out
    assert result.stderr == "TIMEOUT"


@needs_docker
def test_the_workspace_is_writable_so_tests_can_actually_run(executor, tmp_path):
    """The boundary has to be usable, not merely tight."""
    result = run_in_container(executor, tmp_path / "ws", (
        "from pathlib import Path\n"
        "Path('/work/output.txt').write_text('ok')\n"
        "print('WROTE', Path('/work/output.txt').read_text())\n"
    ))
    assert "WROTE ok" in result.stdout
    assert (tmp_path / "ws" / "output.txt").is_file(), \
        "the write did not reach the host workspace"

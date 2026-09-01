"""Layout independence: the same workflow on differently shaped repositories.

The roadmap's Phase 1 exit criterion asks for three Python repositories with
different layouts audited without editing Placebo's source. These build the
three shapes it names and run the real pipeline on each:

    flat        package at the repository root      pkg/
    src         package one level down              src/pkg/
    subpackage  target deep inside a monorepo       services/billing/core/

Only the `.placebo.toml` differs between them, which is the point: the
contract is configuration, and configuration is not source.

This caught a real defect. `PYTHONPATH` was set to the workspace root alone,
so a `src/` layout could not import its own package and every fault came back
INVALID. Placebo would have reported a confident-looking census for a
repository it had never successfully executed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Pure, deterministic, and deliberately only half tested.
OPS = textwrap.dedent("""\
    def clamp(value, low, high):
        if value < low:
            return low
        if value > high:
            return high
        return value


    def sign(value):
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0
    """)

# Covers clamp, never calls sign.
SUITE = textwrap.dedent("""\
    from {module} import clamp


    def test_clamp_inside():
        assert clamp(5, 0, 10) == 5


    def test_clamp_below():
        assert clamp(-3, 0, 10) == 0
    """)


def cli(*argv: str) -> tuple[int, str]:
    from placebo.cli import main

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def build(root: Path, layout: str, name: str) -> Path:
    """Create one repository in the requested shape."""
    # `packages` lists the directories that carry an __init__.py. `src` is
    # deliberately absent from the src layout: it is a path entry, not a
    # package, and making it one would change which directory is importable.
    shapes = {
        "flat": dict(
            pkg_dir="pkg", module="pkg.ops", source_roots=["pkg"],
            target="pkg/ops.py", packages=["pkg"]),
        "src": dict(
            pkg_dir="src/pkg", module="pkg.ops", source_roots=["src"],
            target="src/pkg/ops.py", packages=["src/pkg"]),
        "subpackage": dict(
            pkg_dir="services/billing/core",
            module="services.billing.core.ops", source_roots=["services"],
            target="services/billing/core/ops.py",
            packages=["services", "services/billing", "services/billing/core"]),
    }
    if layout not in shapes:  # pragma: no cover - typo in a parametrisation
        raise ValueError(layout)
    shape = shapes[layout]
    module, source_roots, target = (
        shape["module"], shape["source_roots"], shape["target"])

    pkg_dir = root / shape["pkg_dir"]
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "ops.py").write_text(OPS, encoding="utf-8")
    for package in shape["packages"]:
        (root / package / "__init__.py").write_text("", encoding="utf-8")

    (root / "tests").mkdir()
    (root / "tests" / "test_ops.py").write_text(
        SUITE.format(module=module), encoding="utf-8")

    (root / ".placebo.toml").write_text(textwrap.dedent(f"""\
        version = 1
        name = "{name}"
        language = "python"
        test_command = ["python", "-m", "pytest", "-q"]
        source_roots = {json.dumps(source_roots)}
        test_roots = ["tests"]
        mutation_targets = ["{target}"]
        import_names = ["{module.split('.')[0]}"]
        timeout_seconds = 60
        """), encoding="utf-8")
    return root


def cleanup(name: str) -> None:
    paths = [
        ROOT / "artifacts" / f"census_{name}.json",
        ROOT / "artifacts" / f"survivor_triage_{name}.json",
        *(ROOT / ".placebo-cache").glob(f"{name}.sqlite*"),
    ]
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except PermissionError:  # pragma: no cover - Windows WAL lag
            pass


LAYOUTS = ["flat", "src", "subpackage"]

# Subject names decide the census path and the runner's workspace directory, so
# two processes using the same name would delete each other's workspace
# mid-run. Including the pid keeps concurrent runs isolated.
_RUN = os.getpid()


def subject_name(prefix: str, layout: str) -> str:
    return f"{prefix}{layout}{_RUN}"


# -- import path resolution ------------------------------------------------


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_runner_resolves_an_importable_path(tmp_path, layout):
    """A source root that is itself a package is imported from its parent; one
    that merely contains packages is imported directly."""
    from placebo.config import load
    from placebo.verification.runner import SubjectRunner

    repo = build(tmp_path, layout, subject_name("lay", layout))
    config = load(repo)
    runner = SubjectRunner(repo, tmp_path / "ws",
                           source_roots=config.source_roots)
    runner.prepare()

    paths = [Path(p) for p in runner.import_paths()]
    assert runner.workspace in paths
    if layout == "src":
        assert runner.workspace / "src" in paths, "src must be importable"
    if layout == "flat":
        # `pkg` is a package, so its parent (the workspace) is the import root.
        assert runner.workspace / "pkg" not in paths


def test_a_missing_source_root_is_skipped_rather_than_added(tmp_path):
    from placebo.verification.runner import SubjectRunner

    runner = SubjectRunner(tmp_path, tmp_path / "ws",
                           source_roots=("does_not_exist",))
    runner.prepare()
    assert runner.import_paths() == [str(runner.workspace)]


def test_import_paths_are_deduplicated(tmp_path):
    from placebo.verification.runner import SubjectRunner

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    runner = SubjectRunner(tmp_path, tmp_path / "ws", source_roots=("pkg", "pkg"))
    runner.prepare()
    assert len(runner.import_paths()) == len(set(runner.import_paths()))


# -- the whole workflow, per layout ----------------------------------------


@pytest.mark.parametrize("layout", LAYOUTS)
def test_doctor_supports_every_layout(tmp_path, layout):
    name = subject_name("doc", layout)
    repo = build(tmp_path, layout, name)
    try:
        code, out = cli("doctor", str(repo), "--quick")
        assert code == 0, out
        assert "SUPPORTED" in out
    finally:
        cleanup(name)


@pytest.mark.slow
@pytest.mark.parametrize("layout", LAYOUTS)
def test_census_executes_the_suite_in_every_layout(tmp_path, layout):
    """The regression that motivated this file.

    With the wrong import path the subject cannot be imported, so pytest fails
    to collect and every fault is classified INVALID. A census of only invalid
    faults is not a slower answer, it is a meaningless one, so this asserts
    that real killed and survived verdicts came back.
    """
    name = subject_name("cen", layout)
    repo = build(tmp_path, layout, name)
    try:
        code, out = cli("census", str(repo), "--workers", "2")
        assert code == 0, out

        stored = json.loads(
            (ROOT / "artifacts" / f"census_{name}.json").read_text(encoding="utf-8")
        )
        statuses = {run["status"] for run in stored.values()}
        assert "killed" in statuses, f"{layout}: no fault was ever detected"
        assert "survived" in statuses, f"{layout}: the untested function left no gap"
        assert "invalid" not in statuses, f"{layout}: the subject failed to import"
    finally:
        cleanup(name)


@pytest.mark.slow
@pytest.mark.parametrize("layout", LAYOUTS)
def test_audit_credits_a_gap_closing_test_in_every_layout(tmp_path, layout):
    name = subject_name("aud", layout)
    repo = build(tmp_path, layout, name)
    module = {
        "flat": "pkg.ops",
        "src": "pkg.ops",
        "subpackage": "services.billing.core.ops",
    }[layout]
    try:
        assert cli("census", str(repo), "--workers", "2")[0] == 0

        patch = repo / "candidate.py"
        patch.write_text(textwrap.dedent(f"""\
            from {module} import clamp, sign


            def test_sign_negative():
                assert sign(-4) == -1


            def test_clamp_again():
                assert clamp(5, 0, 10) == 5
            """), encoding="utf-8")

        code, out = cli("audit", str(patch), "--repo", str(repo))
        assert code == 0, out
        assert "VALUABLE" in out, f"{layout}: the sign test closes a real gap"
        assert "REDUNDANT_WITH_EXISTING" in out, f"{layout}: the clamp test repeats"
    finally:
        cleanup(name)


@pytest.mark.slow
def test_the_same_workflow_runs_on_all_three_layouts(tmp_path):
    """The exit criterion stated directly: doctor, census and audit succeed on
    three differently shaped repositories, with only configuration differing."""
    results = {}
    for layout in LAYOUTS:
        name = subject_name("all", layout)
        repo = build(tmp_path / layout, layout, name)
        try:
            doctor_code, _ = cli("doctor", str(repo), "--quick")
            census_code, _ = cli("census", str(repo), "--workers", "2")

            patch = repo / "c.py"
            module = ("services.billing.core.ops" if layout == "subpackage"
                      else "pkg.ops")
            patch.write_text(
                f"from {module} import sign\n\n\n"
                "def test_sign():\n    assert sign(-4) == -1\n", encoding="utf-8")
            audit_code, audit_out = cli("audit", str(patch), "--repo", str(repo))

            results[layout] = (doctor_code, census_code, audit_code,
                               "VALUABLE" in audit_out)
        finally:
            cleanup(name)

    assert results == {
        layout: (0, 0, 0, True) for layout in LAYOUTS
    }, f"not every layout completed the workflow: {results}"

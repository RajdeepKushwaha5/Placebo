"""Tests for repository-independent operation.

These guard the seam that makes Placebo generic. The claim being defended is
that a second, differently structured repository can be described in
configuration and audited without editing Placebo's source, and that the oracle
probe's allowlist remains a real security boundary once it becomes configurable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from placebo.config import (  # noqa: E402
    CONFIG_NAME,
    ConfigError,
    SubjectConfig,
    load,
    suggest,
)
from placebo.doctor import diagnose  # noqa: E402
from placebo.verification.prober import (  # noqa: E402
    DEFAULT_ALLOWED_NAMES,
    _is_safe_probe,
    extract_expressions,
)


# -- configuration ---------------------------------------------------------


def test_both_vendored_subjects_are_configured():
    """The generic path must work for more than the original subject."""
    for relative in ("subject", "subjects/inflection"):
        config = load(ROOT / relative)
        assert config.resolved_targets(), f"{relative} resolved no mutation targets"
        assert config.import_names, f"{relative} declared no probe allowlist"


def test_config_targets_resolve_to_real_files():
    config = load(ROOT / "subject")
    for target in config.resolved_targets():
        assert (config.root / target).is_file()


def test_missing_config_raises_actionable_error(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        load(tmp_path)
    message = str(excinfo.value)
    assert CONFIG_NAME in message
    assert "doctor" in message, "the error should say how to fix it"


def test_yaml_config_is_rejected_with_a_reason(tmp_path):
    """PyYAML is not a dependency, so a .yml must not fail silently."""
    (tmp_path / ".placebo.yml").write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load(tmp_path)
    assert ".placebo.toml" in str(excinfo.value)


def test_unsupported_language_is_rejected(tmp_path):
    (tmp_path / CONFIG_NAME).write_text(
        'version = 1\nlanguage = "rust"\nmutation_targets = ["src/*.rs"]\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="not supported"):
        load(tmp_path)


def test_malformed_toml_is_rejected(tmp_path):
    (tmp_path / CONFIG_NAME).write_text("version = = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load(tmp_path)


def test_missing_required_key_is_named(tmp_path):
    (tmp_path / CONFIG_NAME).write_text('version = 1\nname = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="mutation_targets"):
        load(tmp_path)


def test_suggested_config_parses(tmp_path):
    """--init output must be loadable, not just printable."""
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    (tmp_path / CONFIG_NAME).write_text(suggest(tmp_path), encoding="utf-8")
    config = load(tmp_path)
    assert config.language == "python"
    assert config.test_roots == ("tests",)


# -- the probe allowlist is a security boundary ----------------------------


def test_probe_rejects_names_outside_the_allowlist():
    import ast

    allowed = ("inflection",)
    assert _is_safe_probe(ast.parse('inflection.camelize("a_b")', mode="eval"), allowed)
    # A name legal for another repository must not be legal for this one.
    assert not _is_safe_probe(ast.parse('semver.Version.parse("1.0.0")', mode="eval"), allowed)


@pytest.mark.parametrize("hostile", [
    '__import__("os").system("echo x")',
    'open("/etc/passwd").read()',
    'eval("1+1")',
    'semver.__class__.__mro__',
    '().__class__.__bases__',
])
def test_probe_rejects_hostile_expressions(hostile):
    """Making the allowlist configurable must not weaken it."""
    assert extract_expressions(hostile, allowed_names=("semver", "os")) == []


def test_probe_allowlist_defaults_preserve_original_behaviour():
    assert DEFAULT_ALLOWED_NAMES == ("semver",)
    assert extract_expressions('semver.Version.parse("1.2.3")')
    assert extract_expressions("inflection.camelize('a')") == []


# -- doctor ----------------------------------------------------------------


def test_doctor_reports_supported_for_a_configured_subject():
    report = diagnose(ROOT / "subject", quick=True)
    assert report.supported
    assert report.config is not None
    assert any(f.name == "faults can be enumerated" and f.ok for f in report.findings)


def test_doctor_reports_unsupported_without_config(tmp_path):
    report = diagnose(tmp_path, quick=True)
    assert not report.supported
    failing = [f for f in report.findings if not f.ok and f.blocking]
    assert failing, "an unconfigured repository must produce a blocking finding"
    assert all(f.remedy for f in failing), "every blocking failure needs a remedy"


def test_doctor_flags_a_missing_source_root(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / CONFIG_NAME).write_text(
        'version = 1\n'
        'name = "t"\n'
        'source_roots = ["does_not_exist"]\n'
        'test_roots = ["tests"]\n'
        'mutation_targets = ["pkg/m.py"]\n'
        'import_names = ["pkg"]\n',
        encoding="utf-8",
    )
    report = diagnose(tmp_path, quick=True)
    assert not report.supported
    finding = next(f for f in report.findings if f.name == "source roots exist")
    assert not finding.ok
    assert "does_not_exist" in finding.remedy


def test_doctor_never_raises_on_a_hostile_repository(tmp_path):
    """Unsupported input must produce findings, not a traceback."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "broken.py").write_text("def (((\n", encoding="utf-8")
    (tmp_path / CONFIG_NAME).write_text(
        'version = 1\nname = "t"\nmutation_targets = ["pkg/broken.py"]\n',
        encoding="utf-8",
    )
    report = diagnose(tmp_path, quick=True)
    assert isinstance(report.to_dict(), dict)
    assert not report.supported


def test_doctor_report_is_json_serialisable():
    import json

    report = diagnose(ROOT / "subjects/inflection", quick=True)
    json.dumps(report.to_dict())

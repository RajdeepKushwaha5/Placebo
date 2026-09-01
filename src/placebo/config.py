"""Repository contract: what Placebo needs to know about a subject.

Why this exists
---------------
Placebo's commands read as though they work on any repository, but the oracle
probe, the counterexample domains and the CLI all carried hardcoded knowledge of
the vendored `semver` checkout. That is a product-truth problem: the tool looked
general and was not. This module is the seam that makes the generic parts
generic, so subject-specific knowledge lives in configuration and adapters
rather than in the engine.

Why TOML and not YAML
---------------------
Placebo pins exactly three dependencies and its engine imports only the standard
library. `tomllib` has been stdlib since Python 3.11, whereas PyYAML would be a
fourth dependency bought purely for a config file. A `.placebo.yml` is detected
and rejected with an actionable message rather than silently ignored.

A repository is described by `.placebo.toml` at its root:

    version = 1
    name = "semver"
    language = "python"
    commit = "6adf8765..."
    test_command = ["python", "-m", "pytest", "-q"]
    source_roots = ["semver"]
    test_roots = ["tests"]
    mutation_targets = ["semver/version.py"]
    import_names = ["semver"]
    timeout_seconds = 60
"""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_NAME = ".placebo.toml"
LEGACY_NAMES = (".placebo.yml", ".placebo.yaml")

SUPPORTED_LANGUAGES = {"python"}


class ConfigError(Exception):
    """A repository cannot be audited, with a reason a human can act on."""


@dataclass(frozen=True)
class SubjectConfig:
    """Everything Placebo needs in order to audit one repository."""

    name: str
    root: Path
    commit: str = ""
    language: str = "python"
    test_command: tuple[str, ...] = ("python", "-m", "pytest", "-q")
    source_roots: tuple[str, ...] = ()
    test_roots: tuple[str, ...] = ("tests",)
    mutation_targets: tuple[str, ...] = ()
    #   Names the oracle probe may reference. This is a security boundary as
    #   well as a convenience: the probe rejects any name not listed here.
    import_names: tuple[str, ...] = ()
    timeout_seconds: int = 60
    adapter: str = "generic"
    notes: str = ""

    # -- derived ---------------------------------------------------------

    def resolved_targets(self) -> list[str]:
        """Mutation target files, expanding globs against the repository."""
        found: list[str] = []
        for pattern in self.mutation_targets:
            if any(ch in pattern for ch in "*?["):
                for path in sorted(self.root.glob(pattern)):
                    if path.is_file() and path.suffix == ".py":
                        found.append(path.relative_to(self.root).as_posix())
            else:
                candidate = self.root / pattern
                if candidate.is_file():
                    found.append(pattern)
        # Deduplicate while keeping a deterministic order.
        seen: set[str] = set()
        ordered: list[str] = []
        for item in found:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    def is_probe_name_allowed(self, name: str) -> bool:
        """Whether the oracle probe may reference this top-level name."""
        return name in self.import_names

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["root"] = str(self.root)
        for key in ("test_command", "source_roots", "test_roots",
                    "mutation_targets", "import_names"):
            payload[key] = list(getattr(self, key))
        return payload


def _require(data: dict, key: str, path: Path):
    if key not in data:
        raise ConfigError(
            f"{path}: missing required key '{key}'. "
            f"See docs/REPOSITORY_SUPPORT.md for the full contract."
        )
    return data[key]


def _as_tuple(value, key: str, path: Path) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    raise ConfigError(f"{path}: '{key}' must be a string or a list of strings.")


def load(root: Path) -> SubjectConfig:
    """Read `.placebo.toml` from a repository root.

    Raises ConfigError with an actionable message rather than a traceback when
    the repository cannot be described.
    """
    root = Path(root).resolve()
    path = root / CONFIG_NAME

    if not path.is_file():
        for legacy in LEGACY_NAMES:
            if (root / legacy).is_file():
                raise ConfigError(
                    f"{root / legacy} found, but Placebo reads {CONFIG_NAME}. "
                    "TOML is used because it is in the standard library; YAML "
                    "would add a dependency. Rename and convert the file."
                )
        raise ConfigError(
            f"No {CONFIG_NAME} in {root}. Create one describing how to test "
            "this repository, or run 'placebo doctor <repo> --init' to write a "
            "starting point."
        )

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML ({exc}).") from exc

    version = data.get("version", 1)
    if version != 1:
        raise ConfigError(
            f"{path}: unsupported config version {version!r}; this build reads version 1."
        )

    language = data.get("language", "python")
    if language not in SUPPORTED_LANGUAGES:
        raise ConfigError(
            f"{path}: language {language!r} is not supported. "
            f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}. "
            "Placebo's mutation engine is a Python AST engine; other languages "
            "need a new engine, not a config change."
        )

    return SubjectConfig(
        name=data.get("name", root.name),
        root=root,
        commit=str(data.get("commit", "")),
        language=language,
        test_command=_as_tuple(
            data.get("test_command", ["python", "-m", "pytest", "-q"]),
            "test_command", path),
        source_roots=_as_tuple(data.get("source_roots", []), "source_roots", path),
        test_roots=_as_tuple(data.get("test_roots", ["tests"]), "test_roots", path),
        mutation_targets=_as_tuple(
            _require(data, "mutation_targets", path), "mutation_targets", path),
        import_names=_as_tuple(data.get("import_names", []), "import_names", path),
        timeout_seconds=int(data.get("timeout_seconds", 60)),
        adapter=str(data.get("adapter", "generic")),
        notes=str(data.get("notes", "")),
    )


def discover(start: Path) -> SubjectConfig:
    """Find the nearest `.placebo.toml` at or above `start`."""
    start = Path(start).resolve()
    for candidate in (start, *start.parents):
        if (candidate / CONFIG_NAME).is_file():
            return load(candidate)
    raise ConfigError(
        f"No {CONFIG_NAME} found in {start} or any parent directory."
    )


TEMPLATE = """\
# Placebo repository contract. See docs/REPOSITORY_SUPPORT.md.
version = 1
name = "{name}"
language = "python"

# Pin the revision the evidence refers to. Leave empty for a working tree.
commit = ""

# How to run the existing test suite.
test_command = ["python", "-m", "pytest", "-q"]

# Where the package and its tests live, relative to this file.
source_roots = [{source_roots}]
test_roots = [{test_roots}]

# Files to inject faults into. Globs are allowed.
mutation_targets = [{mutation_targets}]

# Top-level names the oracle probe may reference. This is a security
# boundary: the probe rejects every other name.
import_names = [{import_names}]

timeout_seconds = 60
"""


def suggest(root: Path) -> str:
    """Best-effort starting config, inferred from the repository layout."""
    root = Path(root).resolve()

    def quoted(items) -> str:
        return ", ".join(f'"{i}"' for i in items)

    source_roots: list[str] = []
    for candidate in ("src", root.name.replace("-", "_"), root.name):
        if (root / candidate).is_dir():
            source_roots.append(candidate)
            break
    if not source_roots:
        packages = [
            p.parent.name for p in sorted(root.glob("*/__init__.py"))
            if p.parent.name not in {"tests", "test", "docs"}
        ]
        source_roots = packages[:1]

    test_roots = [d for d in ("tests", "test") if (root / d).is_dir()] or ["tests"]

    targets: list[str] = []
    for source in source_roots:
        base = root / source
        if base.is_dir():
            nested = [p for p in sorted(base.glob("*/__init__.py"))]
            targets.append(
                f"{source}/{nested[0].parent.name}/*.py" if nested else f"{source}/*.py"
            )

    imports = [Path(s).name for s in source_roots if s != "src"]
    if not imports:
        for source in source_roots:
            base = root / source
            packages = [p.parent.name for p in sorted(base.glob("*/__init__.py"))]
            imports.extend(packages[:1])

    return TEMPLATE.format(
        name=root.name,
        source_roots=quoted(source_roots),
        test_roots=quoted(test_roots),
        mutation_targets=quoted(targets or ["src/**/*.py"]),
        import_names=quoted(imports or [root.name]),
    )

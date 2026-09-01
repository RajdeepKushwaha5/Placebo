"""Oracle probe: evaluate expressions against real code and report what happens.

Motivation, straight from measurement. In the mutant-aware condition, 18 of 21
rejections were ``CLEAN_HEAD_FAILED``: the model picked reasonable inputs but
asserted a *wrong expected value*, and could not repair it even when handed the
exact assertion diff.

Guessing a return value is the one part of test authoring that never needs a
language model, because the correct implementation is right there and can be
executed. This module executes candidate expressions against clean HEAD and
against the mutant, so the agent contributes what it is actually good at --
choosing inputs that expose the fault -- and the expected value is *observed*
rather than predicted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import ast
from dataclasses import dataclass

from ..mutation.models import Mutant
from .runner import SubjectRunner

# Top-level names a probe expression may reference. Callers with a
# repository config pass its declared import_names; the default keeps
# the vendored semver subject working unchanged.
DEFAULT_ALLOWED_NAMES: tuple[str, ...] = ("semver",)

_PROBE_SCRIPT = '''\
import json, sys
sys.path.insert(0, {workspace!r})
for _name in json.loads({modules!r}):
    globals()[_name] = __import__(_name)

# A minimal builtins whitelist. Passing an empty __builtins__ removes
# str/repr/len, which silently turned every `str(...)` probe into a
# NameError on BOTH sides - so it never distinguished anything and the
# search quietly lost most of its reach. Constructors and inspection
# only: no import, open, eval, exec, getattr or compile.
_SAFE = {{
    "str": str, "repr": repr, "len": len, "int": int, "float": float,
    "bool": bool, "tuple": tuple, "list": list, "dict": dict, "set": set,
    "sorted": sorted, "type": type, "abs": abs, "min": min, "max": max,
}}

expressions = json.loads({payload!r})
out = []
for expr in expressions:
    try:
        value = eval(expr, {{**{{n: globals()[n] for n in json.loads({modules!r})}},
                             "__builtins__": _SAFE}})
        out.append({{"expr": expr, "ok": True, "repr": repr(value)}})
    except Exception as exc:
        out.append({{"expr": expr, "ok": False,
                     "repr": f"{{type(exc).__name__}}: {{exc}}"}})
print("PLACEBO_PROBE_JSON" + json.dumps(out))
'''


@dataclass
class Observation:
    """What one expression evaluates to on clean code vs. with the fault."""

    expr: str
    clean_repr: str
    clean_ok: bool
    mutant_repr: str
    mutant_ok: bool

    @property
    def distinguishes(self) -> bool:
        """True when this expression actually separates correct from buggy."""
        return (self.clean_repr != self.mutant_repr) or (self.clean_ok != self.mutant_ok)

    def to_dict(self) -> dict:
        return {
            "expr": self.expr,
            "clean": self.clean_repr,
            "mutant": self.mutant_repr,
            "distinguishes": self.distinguishes,
        }


def _evaluate(
    runner: SubjectRunner,
    expressions: list[str],
    timeout_s: int = 120,
    allowed_names: tuple[str, ...] = DEFAULT_ALLOWED_NAMES,
) -> list[dict]:
    """Run expressions inside the workspace and return their reprs."""
    if not expressions:
        return []
    script = _PROBE_SCRIPT.format(
        workspace=str(runner.workspace),
        payload=json.dumps(expressions),
        modules=json.dumps(list(allowed_names)),
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(runner.workspace)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=runner.workspace, env=env,
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return [{"expr": e, "ok": False, "repr": "TIMEOUT"} for e in expressions]

    for line in proc.stdout.splitlines():
        if line.startswith("PLACEBO_PROBE_JSON"):
            return json.loads(line[len("PLACEBO_PROBE_JSON"):])
    return [{"expr": e, "ok": False, "repr": "PROBE_FAILED"} for e in expressions]


def observe(
    runner: SubjectRunner,
    mutant: Mutant,
    expressions: list[str],
    allowed_names: tuple[str, ...] = DEFAULT_ALLOWED_NAMES,
) -> list[Observation]:
    """Evaluate each expression on clean HEAD and under the injected fault."""
    clean = _evaluate(runner, expressions, allowed_names=allowed_names)
    with runner.mutated(mutant):
        mutated = _evaluate(runner, expressions, allowed_names=allowed_names)

    by_expr_clean = {r["expr"]: r for r in clean}
    by_expr_mut = {r["expr"]: r for r in mutated}

    observations: list[Observation] = []
    for expr in expressions:
        c = by_expr_clean.get(expr, {"ok": False, "repr": "MISSING"})
        m = by_expr_mut.get(expr, {"ok": False, "repr": "MISSING"})
        observations.append(
            Observation(
                expr=expr,
                clean_repr=c["repr"],
                clean_ok=c["ok"],
                mutant_repr=m["repr"],
                mutant_ok=m["ok"],
            )
        )
    return observations


def synthesise_test(
    mutant: Mutant, observations: list[Observation], fn_name: str
) -> tuple[str, list[Observation]]:
    """Build a test from observations that provably separate clean from buggy.

    The expected values are the ones clean HEAD actually produced, so the test
    cannot fail on correct code by construction. Only expressions that differ
    under the fault are included, so it cannot pass under the fault either.
    """
    useful = [o for o in observations if o.distinguishes]
    if not useful:
        return ("", [])

    lines = [
        "import pytest",
        "import semver",
        "",
        "",
        f"def {fn_name}():",
        f'    """Detects: {mutant.label}"""',
    ]
    for obs in useful:
        if obs.clean_ok:
            lines.append(f"    assert repr({obs.expr}) == {obs.clean_repr!r}")
        else:
            exc_type = obs.clean_repr.split(":")[0]
            lines.append(
                f"    with pytest.raises({exc_type}):\n        {obs.expr}"
            )
    return ("\n".join(lines) + "\n", useful)


def extract_expressions(
    text: str,
    limit: int = 8,
    allowed_names: tuple[str, ...] = DEFAULT_ALLOWED_NAMES,
) -> list[str]:
    """Pull candidate expressions out of a model response.

    Accepts a fenced block or a bare list, one expression per line.
    """
    import re

    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    body = blocks[0] if blocks else text

    expressions: list[str] = []
    for raw in body.splitlines():
        line = raw.strip().lstrip("-*0123456789. ").strip()
        if not line or line.startswith("#"):
            continue
        if not any(name in line for name in allowed_names):
            continue
        # Must parse as one expression from the deliberately small probe DSL.
        # The subprocess is disposable, but it is not an OS sandbox; rejecting
        # names other than ``semver`` and all dunder access keeps model output
        # from reaching files, imports, process APIs or ambient credentials.
        try:
            tree = ast.parse(line, mode="eval")
        except SyntaxError:
            continue
        if not _is_safe_probe(tree, allowed_names):
            continue
        if line not in expressions:
            expressions.append(line)
        if len(expressions) >= limit:
            break
    return expressions


_SAFE_NODES = (
    ast.Expression, ast.Call, ast.Attribute, ast.Name, ast.Load, ast.Constant,
    ast.keyword, ast.Tuple, ast.List, ast.Dict, ast.Subscript, ast.Slice,
    ast.UnaryOp, ast.UAdd, ast.USub, ast.Not, ast.Compare, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
)


def _is_safe_probe(
    tree: ast.AST, allowed_names: tuple[str, ...] = DEFAULT_ALLOWED_NAMES
) -> bool:
    """Validate the tiny expression language accepted by the oracle probe."""
    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            return False
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            return False
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return False
        if isinstance(node, ast.Call):
            # Direct calls such as open(...), eval(...) and __import__(...) are
            # forbidden. Calls must be attributes rooted in a semver expression.
            if not isinstance(node.func, ast.Attribute):
                return False
            if not _rooted_in_allowed(node.func, allowed_names):
                return False
            if any(keyword.arg is None for keyword in node.keywords):
                return False
    return True


def _rooted_in_allowed(node: ast.AST, allowed_names: tuple[str, ...]) -> bool:
    """True when an attribute/call chain ultimately starts at ``semver``."""
    if isinstance(node, ast.Name):
        return node.id in allowed_names
    if isinstance(node, ast.Attribute):
        return _rooted_in_allowed(node.value, allowed_names)
    if isinstance(node, ast.Call):
        return _rooted_in_allowed(node.func, allowed_names)
    if isinstance(node, ast.Subscript):
        return _rooted_in_allowed(node.value, allowed_names)
    return False

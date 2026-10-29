"""Regression tests for Azure Functions worker indexing rules.

These tests guard against silent 0-functions-loaded failures caused by
code patterns that break the worker's parameter validation. See
/memories/repo/azure-functions-worker-indexing.md for the full explanation.

Three known pitfalls:
  1. @wraps + __wrapped__ leaks inner function params → undeclared bindings
  2. `from __future__ import annotations` stringifies binding annotations
  3. Parameterised generics (dict[str,Any]) on binding params
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINTS_DIR = Path(__file__).resolve().parent.parent / "blueprints"
BLUEPRINT_MODULES = sorted(BLUEPRINTS_DIR.glob("*.py"))


@pytest.fixture(
    scope="module",
    params=[("function_app", "full", 28), ("function_app_orch", "orchestrator", 55)],
    ids=["worker", "admission"],
)
def indexed_functions(request: pytest.FixtureRequest) -> tuple[list[dict[str, object]], int]:
    entrypoint, role, count = request.param
    script = (
        "import importlib,inspect,json,sys; "
        "app=importlib.import_module(sys.argv[1]).app; "
        "print(json.dumps([{'name':f.get_function_name(), "
        "'parameters':list(inspect.signature(f.get_user_function()).parameters), "
        "'bindings':[b.name for b in f.get_bindings() if b.name!='$return']} "
        "for f in app.get_functions()]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, entrypoint],
        cwd=ROOT,
        env={**os.environ, "PIPELINE_ROLE": role},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout.splitlines()[-1]), count


# ── 1. No __wrapped__ on any registered function ────────────────────────


def test_no_undeclared_params_in_signatures(indexed_functions):
    """The worker calls inspect.signature() on each function and treats
    every parameter as a binding.  Any parameter that doesn't match a
    declared binding causes FunctionLoadError → 0 functions loaded.

    This catches the @wraps/__wrapped__ pitfall (PR #301) and any other
    decorator that accidentally leaks extra parameters.
    """
    for function in indexed_functions[0]:
        sig_params = set(function["parameters"])
        binding_names = set(function["bindings"])
        extra = sig_params - binding_names
        assert not extra, (
            f"Function {function['name']!r} signature exposes "
            f"parameters {extra} that are not declared bindings {binding_names}. "
            f"The Azure Functions worker will treat these as undeclared bindings "
            f"and refuse to load ANY functions."
        )


# ── 2. No `from __future__ import annotations` in blueprint modules ─────


def test_no_future_annotations_in_blueprints():
    """Blueprint modules must not use `from __future__ import annotations`.
    PEP 563 stringifies annotations; the Azure Functions worker can't
    resolve stringified binding-parameter types at import time, causing
    FunctionLoadError.
    """
    violations = []
    for path in BLUEPRINT_MODULES:
        if path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.iter_child_nodes(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "__future__"
                and any(alias.name == "annotations" for alias in node.names)
            ):
                violations.append(path.name)
    assert not violations, (
        f"These blueprint modules use `from __future__ import annotations` "
        f"which breaks Azure Functions worker indexing: {violations}"
    )


# ── 3. All registered function params map to known binding types ─────────


def test_function_params_are_valid_bindings(indexed_functions):
    """Every parameter on every registered function must correspond to a
    binding.  The worker calls inspect.signature() and treats every param
    as a binding; extra params cause FunctionLoadError.

    We check that no leaked decorator parameters appear in the signature.
    """
    for function in indexed_functions[0]:
        for param_name in function["parameters"]:
            assert param_name != "auth_claims", (
                f"Function {function['name']!r} exposes "
                f"'auth_claims' parameter — __wrapped__ is leaking "
                f"the inner function signature."
            )
            assert param_name != "user_id", (
                f"Function {function['name']!r} exposes "
                f"'user_id' parameter — __wrapped__ is leaking "
                f"the inner function signature."
            )


# ── 4. function_app.py loads and all functions are indexed ───────────────


def test_function_app_loads_all_blueprints(indexed_functions):
    """function_app.py must import cleanly and register a non-zero number
    of functions.  This catches import-time failures.
    """
    assert len(indexed_functions[0]) > 0, (
        "app.get_functions() returned 0 functions — something is wrong with blueprint registration."
    )


def test_function_count_is_expected(indexed_functions):
    """Guard against accidentally dropping functions.  Update the count
    when intentionally adding or removing endpoints.
    """
    functions, expected_count = indexed_functions
    names = sorted(function["name"] for function in functions)
    assert len(functions) == expected_count, f"Expected {expected_count} functions, got {len(functions)}: {names}"

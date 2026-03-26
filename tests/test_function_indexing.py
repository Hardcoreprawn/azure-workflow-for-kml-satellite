"""Regression tests for Azure Functions worker indexing rules.

These tests guard against silent 0-functions-loaded failures caused by
code patterns that break the worker's parameter validation. See
/memories/repo/azure-functions-worker-indexing.md for the full explanation.

Three known pitfalls:
  1. @wraps + __wrapped__ leaks inner function params → undeclared bindings
  2. `from __future__ import annotations` stringifies binding annotations
  3. Parameterised generics (dict[str,Any]) on binding params
"""

import ast
import inspect
from pathlib import Path

BLUEPRINTS_DIR = Path(__file__).resolve().parent.parent / "blueprints"
BLUEPRINT_MODULES = sorted(BLUEPRINTS_DIR.glob("*.py"))

# app.get_functions() has a side-effect: it populates functions_bindings
# which makes subsequent calls raise ValueError (duplicate names).
# Build the list once at module level and share across all tests.
from function_app import app  # noqa: E402

# Clear stale state left by earlier imports so get_functions() succeeds
app.functions_bindings = {}
_ALL_FUNCTIONS = app.get_functions()


# ── 1. No __wrapped__ on any registered function ────────────────────────


def test_no_undeclared_params_in_signatures():
    """The worker calls inspect.signature() on each function and treats
    every parameter as a binding.  Any parameter that doesn't match a
    declared binding causes FunctionLoadError → 0 functions loaded.

    This catches the @wraps/__wrapped__ pitfall (PR #301) and any other
    decorator that accidentally leaks extra parameters.
    """
    for fn_info in _ALL_FUNCTIONS:
        func_obj = fn_info.get_user_function()
        sig_params = set(inspect.signature(func_obj).parameters)
        binding_names = {b.name for b in fn_info.get_bindings() if b.name != "$return"}
        extra = sig_params - binding_names
        assert not extra, (
            f"Function {fn_info.get_function_name()!r} signature exposes "
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


def test_function_params_are_valid_bindings():
    """Every parameter on every registered function must correspond to a
    binding.  The worker calls inspect.signature() and treats every param
    as a binding; extra params cause FunctionLoadError.

    We check that no leaked decorator parameters appear in the signature.
    """
    for fn_info in _ALL_FUNCTIONS:
        func_obj = fn_info.get_user_function()
        sig = inspect.signature(func_obj)
        for param_name in sig.parameters:
            assert param_name != "auth_claims", (
                f"Function {fn_info.get_function_name()!r} exposes "
                f"'auth_claims' parameter — __wrapped__ is leaking "
                f"the inner function signature."
            )
            assert param_name != "user_id", (
                f"Function {fn_info.get_function_name()!r} exposes "
                f"'user_id' parameter — __wrapped__ is leaking "
                f"the inner function signature."
            )


# ── 4. function_app.py loads and all functions are indexed ───────────────


def test_function_app_loads_all_blueprints():
    """function_app.py must import cleanly and register a non-zero number
    of functions.  This catches import-time failures.
    """
    assert len(_ALL_FUNCTIONS) > 0, (
        "function_app.app.get_functions() returned 0 functions — "
        "something is wrong with blueprint registration."
    )


def test_function_count_is_expected():
    """Guard against accidentally dropping functions.  Update the count
    when intentionally adding or removing endpoints.
    """
    names = sorted(fn.get_function_name() or "" for fn in _ALL_FUNCTIONS)
    # As of PR #301: 32 functions.  Update when adding/removing.
    assert len(_ALL_FUNCTIONS) >= 30, (
        f"Expected at least 30 registered functions, got {len(_ALL_FUNCTIONS)}: {names}"
    )

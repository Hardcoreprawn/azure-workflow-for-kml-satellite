"""Runtime indexing contract tests for Azure FunctionApp registration.

These tests execute the actual `FunctionApp` object rather than only checking
source text, so we catch cases where decorators exist but runtime metadata
is empty.
"""

from __future__ import annotations

import pytest

import function_app


@pytest.fixture(scope="module")
def indexed_function_names() -> set[str]:
    """Resolve FunctionApp metadata once to avoid duplicate validation side effects."""
    functions = function_app.app.get_functions()
    return {fn.get_function_name() for fn in functions}


def test_function_app_indexes_nonzero_functions(indexed_function_names: set[str]) -> None:
    """The FunctionApp should expose indexed functions at import time."""
    assert len(indexed_function_names) > 0, "FunctionApp indexed zero functions"


def test_critical_functions_are_indexed(indexed_function_names: set[str]) -> None:
    """Critical trigger and API contract endpoints must be indexed."""
    assert "kml_blob_trigger" in indexed_function_names
    assert "api_contract" in indexed_function_names
    assert "health_liveness" in indexed_function_names
    assert "health_readiness" in indexed_function_names

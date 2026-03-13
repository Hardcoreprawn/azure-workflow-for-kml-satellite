"""Contracts for the live E2E workflow auth configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def e2e_workflow() -> dict[str, Any]:
    path = WORKSPACE_ROOT / ".github" / "workflows" / "e2e.yml"
    assert path.exists(), f"e2e.yml missing at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _get_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return workflow.get("jobs", {}).get("e2e-test", {}).get("steps", [])


def _find_step(steps: list[dict[str, Any]], name_fragment: str) -> dict[str, Any] | None:
    fragment = name_fragment.lower()
    return next((step for step in steps if fragment in step.get("name", "").lower()), None)


def test_resolve_step_exports_storage_connection_string(e2e_workflow: dict[str, Any]) -> None:
    steps = _get_steps(e2e_workflow)
    resolve = _find_step(steps, "resolve live environment values")
    assert resolve is not None, "Resolve live environment values step missing"

    run_script = str(resolve.get("run", ""))
    assert "AzureWebJobsStorage" in run_script, (
        "E2E workflow must resolve AzureWebJobsStorage app setting for blob auth"
    )
    assert "storage_connection_string=" in run_script, (
        "E2E workflow must export storage_connection_string output"
    )
    assert "::add-mask::${STORAGE_CONNECTION_STRING}" in run_script, (
        "E2E workflow must mask storage connection string in logs"
    )
    assert 'if [[ "$STORAGE_CONNECTION_STRING" != *"AccountKey="* ]]; then' in run_script, (
        "E2E workflow must detect non-key-based AzureWebJobsStorage values"
    )
    assert "az storage account keys list" in run_script, (
        "E2E workflow must fallback to storage account key resolution when needed"
    )


def test_run_step_injects_storage_connection_string(e2e_workflow: dict[str, Any]) -> None:
    steps = _get_steps(e2e_workflow)
    run_step = _find_step(steps, "run live e2e tests")
    assert run_step is not None, "Run live E2E tests step missing"

    env_block = run_step.get("env", {})
    assert env_block.get("E2E_STORAGE_CONNECTION_STRING") == (
        "${{ steps.env.outputs.storage_connection_string }}"
    )

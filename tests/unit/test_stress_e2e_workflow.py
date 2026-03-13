"""Contracts for stress E2E workflow auth and test wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def stress_workflow() -> dict[str, Any]:
    path = WORKSPACE_ROOT / ".github" / "workflows" / "stress-e2e.yml"
    assert path.exists(), f"stress-e2e.yml missing at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _get_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return workflow.get("jobs", {}).get("stress-e2e", {}).get("steps", [])


def _find_step(steps: list[dict[str, Any]], name_fragment: str) -> dict[str, Any] | None:
    fragment = name_fragment.lower()
    return next((step for step in steps if fragment in step.get("name", "").lower()), None)


def test_resolve_step_has_resilient_storage_and_host_key_fallbacks(
    stress_workflow: dict[str, Any],
) -> None:
    steps = _get_steps(stress_workflow)
    resolve = _find_step(steps, "resolve live environment values")
    assert resolve is not None, "Resolve live environment values step missing"

    run_script = str(resolve.get("run", ""))
    assert "AzureWebJobsStorage" in run_script
    assert "az storage account keys list" in run_script
    assert "/host/default/listKeys?api-version=2024-04-01" in run_script
    assert '--query "masterKey" -o tsv' in run_script
    assert '--query "functionKeys.default" -o tsv' in run_script
    assert "storage_connection_string=" in run_script


def test_stress_step_injects_connection_string_env(stress_workflow: dict[str, Any]) -> None:
    steps = _get_steps(stress_workflow)
    run_step = _find_step(steps, "run concurrent stress test")
    assert run_step is not None, "Run concurrent stress test step missing"

    env_block = run_step.get("env", {})
    assert env_block.get("E2E_STORAGE_CONNECTION_STRING") == (
        "${{ steps.env.outputs.storage_connection_string }}"
    )

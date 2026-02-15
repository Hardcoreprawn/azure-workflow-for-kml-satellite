"""Tests for the deploy workflow (deploy.yml).

Validates that the GitHub Actions deploy workflow contains the required
steps to successfully deploy to Azure Functions Flex Consumption:

1. Python dependencies are pre-installed into the deployment package so
   the zip is ready-to-run (Flex Consumption does not perform remote-build
   by default).

2. A readiness check polls for function registration before enabling the
   Event Grid subscription, preventing "Destination endpoint not found"
   errors when Azure cannot validate the webhook endpoint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WORKFLOW_DIR = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows"


@pytest.fixture(scope="module")
def deploy_workflow() -> dict[str, Any]:
    """Parse deploy.yml into a dict."""
    path = WORKFLOW_DIR / "deploy.yml"
    assert path.exists(), f"deploy.yml not found at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _get_steps(workflow: dict[str, Any], job_name: str = "deploy-dev") -> list[dict[str, Any]]:
    """Return the steps list for a given job."""
    return workflow.get("jobs", {}).get(job_name, {}).get("steps", [])


def _find_step(steps: list[dict[str, Any]], name_fragment: str) -> dict[str, Any] | None:
    """Find a step whose 'name' contains the given fragment (case-insensitive)."""
    fragment_lower = name_fragment.lower()
    return next(
        (s for s in steps if fragment_lower in s.get("name", "").lower()),
        None,
    )


# ---------------------------------------------------------------------------
# Test: Dependency installation in deployment package
# ---------------------------------------------------------------------------


class TestDependencyInstallation:
    """Verify the workflow pre-installs Python dependencies."""

    def test_pip_install_step_exists(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must contain a step that runs pip install."""
        steps = _get_steps(deploy_workflow)
        has_pip = any("pip install" in s.get("run", "") for s in steps if "run" in s)
        assert has_pip, (
            "No step runs 'pip install' — Flex Consumption requires a "
            "ready-to-run package with dependencies pre-installed"
        )

    def test_pip_install_targets_python_packages(self, deploy_workflow: dict[str, Any]) -> None:
        """pip install must target .python_packages/lib/site-packages.

        Azure Functions Python worker looks for dependencies in this
        specific directory inside the deployment zip.
        """
        steps = _get_steps(deploy_workflow)
        pip_steps = [s.get("run", "") for s in steps if "pip install" in s.get("run", "")]
        assert any(".python_packages/lib/site-packages" in step_run for step_run in pip_steps), (
            "pip install must use --target='.python_packages/lib/site-packages' "
            "so Azure Functions can find the dependencies"
        )

    def test_requirements_txt_used(self, deploy_workflow: dict[str, Any]) -> None:
        """pip install must reference requirements.txt."""
        steps = _get_steps(deploy_workflow)
        pip_steps = [s.get("run", "") for s in steps if "pip install" in s.get("run", "")]
        assert any("requirements.txt" in step_run for step_run in pip_steps), (
            "pip install must reference requirements.txt"
        )

    def test_python_setup_step_present(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must set up Python before building the package."""
        steps = _get_steps(deploy_workflow)
        python_step = _find_step(steps, "python")
        assert python_step is not None, "No 'Set up Python' step found"
        # Verify it uses setup-python action
        assert "setup-python" in python_step.get("uses", ""), (
            "Python setup step must use actions/setup-python"
        )


# ---------------------------------------------------------------------------
# Test: Function readiness check before Event Grid subscription
# ---------------------------------------------------------------------------


class TestReadinessCheck:
    """Verify the workflow waits for functions before enabling Event Grid."""

    def test_readiness_step_exists(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must have a step that waits for functions to be discoverable."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None, (
            "No readiness-check step found — the workflow must wait for "
            "functions to be registered before enabling Event Grid"
        )

    def test_readiness_uses_function_list(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check must poll 'az functionapp function list'."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")
        assert "az functionapp function list" in run_script, (
            "Readiness check must use 'az functionapp function list' to "
            "verify functions are registered"
        )

    def test_readiness_has_retry_loop(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check must retry (not just check once)."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")
        # Look for loop constructs: for/while + sleep
        has_loop = "for " in run_script or "while " in run_script
        has_sleep = "sleep" in run_script
        assert has_loop and has_sleep, "Readiness check must include a retry loop with sleep"

    def test_readiness_has_failure_exit(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check must fail the workflow if functions never appear."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")
        assert "exit 1" in run_script, (
            "Readiness check must 'exit 1' if functions are never detected"
        )

    def test_readiness_before_event_grid(self, deploy_workflow: dict[str, Any]) -> None:
        """The readiness check must come BEFORE the Event Grid subscription step."""
        steps = _get_steps(deploy_workflow)
        readiness_idx = None
        event_grid_idx = None

        for i, step in enumerate(steps):
            name = step.get("name", "").lower()
            if readiness_idx is None and ("wait" in name or "discoverable" in name):
                readiness_idx = i
            if event_grid_idx is None and "event grid" in name:
                event_grid_idx = i

        assert readiness_idx is not None, "Readiness check step not found"
        assert event_grid_idx is not None, "Event Grid subscription step not found"
        assert readiness_idx < event_grid_idx, (
            f"Readiness check (step {readiness_idx}) must come before "
            f"Event Grid subscription (step {event_grid_idx})"
        )

"""Tests for OpenTofu apply workflow smoke verification contract.

Issue #131 follow-up: post-deploy smoke checks must verify deployed endpoint
availability and event grid wiring so remote diagnostics are not blind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "tofu-apply.yml"
)


@pytest.fixture(scope="module")
def tofu_apply_workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.exists(), f"tofu-apply.yml not found at {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _job(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    jobs = workflow.get("jobs", {})
    assert name in jobs, f"Expected job '{name}' to exist"
    return jobs[name]


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def _find_step(steps: list[dict[str, Any]], fragment: str) -> dict[str, Any] | None:
    frag = fragment.lower()
    return next((s for s in steps if frag in s.get("name", "").lower()), None)


def test_smoke_test_dev_job_enabled(tofu_apply_workflow: dict[str, Any]) -> None:
    smoke = _job(tofu_apply_workflow, "smoke-test-dev")
    assert smoke.get("needs") == "apply-dev"


def test_smoke_test_prd_job_enabled(tofu_apply_workflow: dict[str, Any]) -> None:
    smoke = _job(tofu_apply_workflow, "smoke-test-prd")
    assert smoke.get("needs") == "apply-prd"


def test_smoke_jobs_check_health_and_readiness(tofu_apply_workflow: dict[str, Any]) -> None:
    for name in ("smoke-test-dev", "smoke-test-prd"):
        steps = _steps(_job(tofu_apply_workflow, name))
        health = _find_step(steps, "health endpoint")
        readiness = _find_step(steps, "readiness endpoint")

        assert health is not None, f"{name} missing health endpoint smoke step"
        assert readiness is not None, f"{name} missing readiness endpoint smoke step"
        assert "curl" in health.get("run", "")
        assert "/api/health" in health.get("run", "")
        assert "curl" in readiness.get("run", "")
        assert "/api/readiness" in readiness.get("run", "")


def test_smoke_jobs_check_contact_form_endpoint(tofu_apply_workflow: dict[str, Any]) -> None:
    for name in ("smoke-test-dev", "smoke-test-prd"):
        steps = _steps(_job(tofu_apply_workflow, name))
        contact = _find_step(steps, "contact form endpoint")
        assert contact is not None, f"{name} missing contact form smoke step"
        run_script = contact.get("run", "")
        assert "/api/contact-form" in run_script
        assert "POST" in run_script
        assert "202" in run_script


def test_smoke_jobs_verify_event_grid_subscription(tofu_apply_workflow: dict[str, Any]) -> None:
    for name in ("smoke-test-dev", "smoke-test-prd"):
        steps = _steps(_job(tofu_apply_workflow, name))
        event_grid = _find_step(steps, "event grid subscription")
        assert event_grid is not None, f"{name} missing Event Grid verification step"
        run_script = event_grid.get("run", "")
        assert "az eventgrid system-topic event-subscription show" in run_script
        assert "provisioningState" in run_script
        assert "Succeeded" in run_script

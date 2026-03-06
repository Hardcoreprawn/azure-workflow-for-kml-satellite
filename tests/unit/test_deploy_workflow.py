"""Tests for the deploy workflow (deploy.yml).

Validates that the GitHub Actions deploy workflow contains the required
steps to build a Docker container image, push it to GitHub Container
Registry (ghcr.io), and deploy it to Azure Functions on Container Apps:

1. The workflow builds a Docker image (with GDAL and native geospatial
   libraries baked in) and pushes it to ghcr.io.

2. The function app container image and Event Grid subscription are
   deployed via a single Bicep deployment that passes the container
   image as a parameter, preventing the image from being reset.

3. A readiness check polls for function registration to confirm the
   deployment succeeded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

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


def _get_job(workflow: dict[str, Any], job_name: str) -> dict[str, Any]:
    """Return a workflow job definition by name."""
    return workflow.get("jobs", {}).get(job_name, {})


# ---------------------------------------------------------------------------
# Test: Container-based deployment
# ---------------------------------------------------------------------------


class TestContainerDeployment:
    """Verify the workflow builds and deploys a Docker container."""

    def test_ghcr_login_step_exists(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must log in to GitHub Container Registry."""
        steps = _get_steps(deploy_workflow)
        login = _find_step(steps, "container registry") or _find_step(steps, "ghcr")
        assert login is not None, "No ghcr.io login step found"
        assert "docker/login-action" in login.get("uses", ""), (
            "GHCR login must use docker/login-action"
        )

    def test_ghcr_login_uses_github_token(self, deploy_workflow: dict[str, Any]) -> None:
        """GHCR login must use GITHUB_TOKEN (not a stored PAT)."""
        steps = _get_steps(deploy_workflow)
        login = _find_step(steps, "container registry") or _find_step(steps, "ghcr")
        assert login is not None
        with_block = login.get("with", {})
        password = with_block.get("password", "")
        assert "GITHUB_TOKEN" in password, (
            "GHCR login must use secrets.GITHUB_TOKEN, not a stored credential"
        )

    def test_docker_build_push_step_exists(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must build and push a Docker image."""
        steps = _get_steps(deploy_workflow)
        build = _find_step(steps, "build and push")
        assert build is not None, "No 'Build and push' step found"
        assert "docker/build-push-action" in build.get("uses", ""), (
            "Build step must use docker/build-push-action"
        )

    def test_docker_push_enabled(self, deploy_workflow: dict[str, Any]) -> None:
        """Docker build step must push the image."""
        steps = _get_steps(deploy_workflow)
        build = _find_step(steps, "build and push")
        assert build is not None
        assert build.get("with", {}).get("push") is True, (
            "docker/build-push-action must have push: true"
        )

    def test_container_deploy_step_exists(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must deploy the container image via Bicep with containerImage param."""
        steps = _get_steps(deploy_workflow)
        deploy = _find_step(steps, "deploy container") or _find_step(steps, "event grid")
        assert deploy is not None, "No container deploy step found"
        run_script = deploy.get("run", "")
        assert "az deployment sub create" in run_script, (
            "Deploy step must use 'az deployment sub create' with Bicep"
        )
        assert "containerImage" in run_script, (
            "Deploy step must pass containerImage parameter to Bicep"
        )

    def test_image_tagged_with_commit_sha(self, deploy_workflow: dict[str, Any]) -> None:
        """Container image metadata must include commit SHA for traceability."""
        steps = _get_steps(deploy_workflow)
        image_step = _find_step(steps, "resolve container image tags") or _find_step(
            steps, "image tag"
        )
        assert image_step is not None, "No image name/tag step found"
        run_script = image_step.get("run", "")
        assert "GITHUB_SHA" in run_script, "Image tag must include the commit SHA for traceability"

    def test_image_tagged_with_semver(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must emit a semantic version tag from pyproject version."""
        steps = _get_steps(deploy_workflow)
        image_step = _find_step(steps, "resolve container image tags")
        assert image_step is not None, "No semantic image tag step found"
        run_script = image_step.get("run", "")
        assert "pyproject.toml" in run_script, "Semantic tag must be derived from project version"
        assert "semver_tag" in run_script, "Workflow must output a semantic version tag"
        assert "v${VERSION}" in run_script, "Semantic tag format must be v<semver>"

    def test_deploy_uses_sha_tag_not_semver(self, deploy_workflow: dict[str, Any]) -> None:
        """Deployment must pin to immutable SHA tag even when semver tags exist."""
        steps = _get_steps(deploy_workflow)
        first_pass = _find_step(steps, "subscription disabled") or _find_step(
            steps, "deploy container image"
        )
        second_pass = _find_step(steps, "enable event grid subscription")
        assert first_pass is not None and second_pass is not None
        first_run = first_pass.get("run", "")
        second_run = second_pass.get("run", "")
        assert "steps.image.outputs.sha_tag" in first_run
        assert "steps.image.outputs.sha_tag" in second_run

    def test_no_functions_action(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must NOT use azure/functions-action (code deploy)."""
        steps = _get_steps(deploy_workflow)
        for step in steps:
            uses = step.get("uses", "")
            assert "azure/functions-action" not in uses or "container" in uses, (
                "Must not use azure/functions-action — container deployment "
                "uses docker/build-push-action + az deployment sub create"
            )

    def test_packages_write_permission(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must have packages:write permission for ghcr.io push."""
        permissions = deploy_workflow.get("permissions", {})
        assert permissions.get("packages") == "write", (
            "Workflow must have 'packages: write' permission to push to ghcr.io"
        )

    def test_dockerfile_in_trigger_paths(self, deploy_workflow: dict[str, Any]) -> None:
        """Dockerfile changes must trigger a deployment."""
        # PyYAML 1.1 can parse bare `on:` as boolean True.
        on_block = deploy_workflow.get("on")
        if not isinstance(on_block, dict):
            fallback = cast(Any, deploy_workflow).get(True, {})
            on_block = fallback if isinstance(fallback, dict) else {}
        paths = on_block.get("push", {}).get("paths", [])
        assert "Dockerfile" in paths, (
            "Dockerfile must be in the trigger paths so image changes trigger deploy"
        )

    def test_workflow_dispatch_exposes_staging_target(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Manual dispatch must support selecting the staging deployment target."""
        on_block = deploy_workflow.get("on")
        if not isinstance(on_block, dict):
            fallback = cast(Any, deploy_workflow).get(True, {})
            on_block = fallback if isinstance(fallback, dict) else {}
        dispatch = on_block.get("workflow_dispatch", {})
        options = dispatch.get("inputs", {}).get("target_environment", {}).get("options", [])
        assert "staging" in options, "workflow_dispatch target_environment must include staging"


class TestStagingDeployment:
    """Verify staging deployment job wiring for integration environment rollout."""

    def test_staging_job_exists(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must define a dedicated staging deployment job."""
        staging = _get_job(deploy_workflow, "deploy-staging")
        assert staging, "deploy-staging job is missing"
        environment = str(staging.get("environment", ""))
        assert "target_environment" in environment

    def test_staging_job_uses_staging_parameters(self, deploy_workflow: dict[str, Any]) -> None:
        """Staging deployment must target staging bicep parameter file and resources."""
        staging = _get_job(deploy_workflow, "deploy-staging")
        assert staging, "deploy-staging job is missing"
        env_block = staging.get("env", {})
        assert env_block.get("PARAM_FILE") == "infra/parameters/staging.bicepparam"
        assert env_block.get("FUNCTION_APP_NAME") == "func-kmlsat-staging"
        assert env_block.get("RESOURCE_GROUP") == "rg-kmlsat-staging"
        assert env_block.get("EVENT_GRID_TOPIC") == "evgt-kmlsat-staging"

    def test_staging_job_runs_only_for_staging_dispatch(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Staging deploy job must be gated behind workflow_dispatch staging target."""
        staging = _get_job(deploy_workflow, "deploy-staging")
        assert staging, "deploy-staging job is missing"
        condition = staging.get("if", "")
        assert "workflow_dispatch" in condition
        assert "target_environment == 'staging'" in condition


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

    def test_readiness_uses_host_status_endpoint(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check must poll authenticated host-status endpoint."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")
        assert "curl" in run_script and "/admin/host/status" in run_script, (
            "Readiness check must call /admin/host/status for authoritative host state"
        )
        assert "x-functions-key" in run_script, "Readiness check must authenticate with host key"
        assert "listKeys" in run_script, "Readiness check must fetch host key via listKeys"

    def test_readiness_checks_running_state(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check must gate on host state=Running."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")
        assert "state" in run_script and "Running" in run_script, (
            "Readiness check must evaluate host state and require Running"
        )

    def test_readiness_has_retry_loop(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check must retry (not just check once)."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")
        has_loop = "for " in run_script or "while " in run_script
        has_sleep = "sleep" in run_script
        assert has_loop and has_sleep, "Readiness check must include a retry loop with sleep"

    def test_readiness_does_not_hard_fail(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check should be advisory; Event Grid enable step handles hard failure."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")
        # Check for warning emission (actual message may vary)
        assert "::warning::" in run_script and "warn" in run_script, (
            "Readiness check should emit warning if functions host is not yet ready"
        )

    def test_event_grid_uses_two_pass_toggle(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must disable then enable Event Grid subscription in two passes."""
        steps = _get_steps(deploy_workflow)

        first_pass = _find_step(steps, "subscription disabled") or _find_step(
            steps, "deploy container image"
        )
        assert first_pass is not None, "First-pass deploy step not found"
        first_run = first_pass.get("run", "")
        assert "enableEventGridSubscription=false" in first_run, (
            "First pass must set enableEventGridSubscription=false"
        )

        second_pass = _find_step(steps, "enable event grid subscription")
        assert second_pass is not None, "Second-pass Event Grid enable step not found"
        second_run = second_pass.get("run", "")
        assert "enableEventGridSubscription=true" in second_run, (
            "Second pass must set enableEventGridSubscription=true"
        )

    def test_event_grid_enable_runs_after_readiness(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness must execute before Event Grid enablement."""
        steps = _get_steps(deploy_workflow)
        readiness_idx = next(
            (i for i, s in enumerate(steps) if "wait" in s.get("name", "").lower()),
            -1,
        )
        enable_idx = next(
            (
                i
                for i, s in enumerate(steps)
                if "enable event grid subscription" in s.get("name", "").lower()
            ),
            -1,
        )
        assert readiness_idx >= 0, "Readiness step not found"
        assert enable_idx >= 0, "Event Grid enable step not found"
        assert readiness_idx < enable_idx, "Readiness step must run before Event Grid enablement"

    def test_event_grid_enable_has_retry_and_failure_exit(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Event Grid enable step must retry with defensive patterns and fail if exhausted."""
        steps = _get_steps(deploy_workflow)
        second_pass = _find_step(steps, "enable event grid subscription")
        assert second_pass is not None, "Second-pass Event Grid enable step not found"
        run_script = second_pass.get("run", "")

        # Must have retry loop (bash for loop)
        assert "for ((i=" in run_script or "for i in" in run_script, (
            "Enable step must include retry loop"
        )

        # Must have backoff mechanism (exponential or fixed)
        assert "sleep" in run_script, "Enable step must back off between retries"
        # Check for wait/backoff logic (variable names may vary)
        has_backoff = "BASE_WAIT" in run_script or "WAIT" in run_script or "* i" in run_script
        assert has_backoff, "Enable step must calculate backoff/wait time"

        # Must have wall-clock timeout (variable naming may vary)
        has_max_duration = "MAX_DURATION" in run_script or "max_duration" in run_script
        assert has_max_duration, "Enable step must have wall-clock timeout"
        assert "ELAPSED" in run_script or "elapsed" in run_script, (
            "Enable step must track elapsed time"
        )

        # Must fail after exhausting retries/timeout
        assert "exit 1" in run_script, "Enable step must fail after exhausting retries"

        # Must have observability (logging attempts)
        assert "Attempt" in run_script or "attempt" in run_script, (
            "Enable step must log attempt number"
        )

    def test_event_grid_enable_has_fail_fast_detection(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Event Grid enable step must detect non-transient errors and fail fast."""
        steps = _get_steps(deploy_workflow)
        second_pass = _find_step(steps, "enable event grid subscription")
        assert second_pass is not None
        run_script = second_pass.get("run", "")

        # Must detect authorization/credential errors
        assert "authorization" in run_script.lower() or "forbidden" in run_script.lower(), (
            "Enable step must detect auth/permission errors for fail-fast"
        )

        # Must detect and skip retries for non-transient errors
        assert "break" in run_script or "exit" in run_script, (
            "Enable step must break loop or exit on non-transient errors"
        )

    def test_readiness_has_wall_clock_timeout(self, deploy_workflow: dict[str, Any]) -> None:
        """Readiness check must have wall-clock timeout, not just attempt count."""
        steps = _get_steps(deploy_workflow)
        readiness = _find_step(steps, "wait") or _find_step(steps, "discoverable")
        assert readiness is not None
        run_script = readiness.get("run", "")

        # Must track elapsed time (case-insensitive check)
        has_elapsed = "ELAPSED" in run_script or "elapsed" in run_script
        assert has_elapsed, "Readiness check must track elapsed time"

        # Must have max duration (variable naming may vary)
        has_max = "MAX_DURATION" in run_script or "max_duration" in run_script
        assert has_max, "Readiness check must have max duration"

        # Must check timeout in loop (using bash's -ge operator)
        assert "-ge" in run_script or ">=" in run_script, (
            "Readiness check must validate elapsed time against timeout"
        )

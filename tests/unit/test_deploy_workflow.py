"""Tests for the deploy workflow (deploy.yml).

Validates that the GitHub Actions deploy workflow contains the required
steps to build a Docker container image, push it to GitHub Container
Registry (ghcr.io), and deploy it to Azure Functions on Container Apps:

1. The workflow builds a Docker image (with GDAL and native geospatial
   libraries baked in) and pushes it to ghcr.io.

2. The function app container image is deployed via Azure CLI command
   'az functionapp config container set', updating the container on the
   existing Function App resource (managed by OpenTofu).

3. A readiness check polls for function registration to confirm the
   deployment succeeded.

4. Event Grid subscription is enabled via direct Azure CLI commands
   after function readiness is verified.
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

    def test_registry_runtime_credentials_use_dedicated_pull_secret(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Runtime DOCKER_REGISTRY app settings must not use expiring GITHUB_TOKEN."""
        steps = _get_steps(deploy_workflow)
        configure = _find_step(steps, "configure registry credentials")
        assert configure is not None, "No registry credential configuration step found"

        run_script = str(configure.get("run", ""))
        assert 'DOCKER_REGISTRY_SERVER_PASSWORD="${{ secrets.GHCR_PULL_TOKEN }}"' in run_script
        assert 'DOCKER_REGISTRY_SERVER_PASSWORD="${{ secrets.GITHUB_TOKEN }}"' not in run_script

    def test_preflight_requires_ghcr_pull_token(self, deploy_workflow: dict[str, Any]) -> None:
        """Pre-flight contract must fail fast if GHCR_PULL_TOKEN is missing."""
        steps = _get_steps(deploy_workflow)
        preflight = _find_step(steps, "pre-flight deployment contract")
        assert preflight is not None, "No pre-flight deployment contract step found"

        env_block = preflight.get("env", {})
        assert env_block.get("GHCR_PULL_TOKEN") == "${{ secrets.GHCR_PULL_TOKEN }}"

        run_script = str(preflight.get("run", ""))
        assert 'require_value "$GHCR_PULL_TOKEN" "GHCR_PULL_TOKEN' in run_script

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
        """Workflow must update Function App container via Azure CLI."""
        steps = _get_steps(deploy_workflow)
        deploy = _find_step(steps, "update function app container") or _find_step(
            steps, "container image"
        )
        assert deploy is not None, "No container update step found"
        run_script = deploy.get("run", "")
        assert "az functionapp config container set" in run_script, (
            "Deploy step must use 'az functionapp config container set' to update Function App"
        )
        assert "FUNCTION_APP_NAME" in run_script or "func-kmlsat" in run_script, (
            "Deploy step must reference the Function App name"
        )
        assert "--image" in run_script or "docker-custom-image-name" in run_script, (
            "Deploy step must pass the custom container image name"
        )

    def test_image_tagged_with_commit_sha(self, deploy_workflow: dict[str, Any]) -> None:
        """Container image must be tagged with the commit SHA for traceability."""
        steps = _get_steps(deploy_workflow)
        image_step = _find_step(steps, "image name") or _find_step(steps, "image tag")
        assert image_step is not None, "No image name/tag step found"
        run_script = image_step.get("run", "")
        assert "source_sha=" in run_script, "Image step must emit a source_sha output"
        assert "$SOURCE_SHA" in run_script, "Image tag must use the resolved source SHA"

    def test_image_step_derives_sha_from_checked_out_source(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Workflow-run deploys must tag and label images using the same SHA that was checked out."""
        steps = _get_steps(deploy_workflow)
        image_step = _find_step(steps, "image name") or _find_step(steps, "image tag")
        assert image_step is not None, "No image name/tag step found"

        env_block = image_step.get("env", {})
        assert (
            env_block.get("SOURCE_SHA")
            == "${{ github.event.workflow_run.head_sha || github.sha }}"
        )

    def test_registry_build_cache_ref_is_set(self, deploy_workflow: dict[str, Any]) -> None:
        """Deploy workflow must publish a stable registry cache ref for Docker BuildKit reuse."""
        steps = _get_steps(deploy_workflow)
        image_step = _find_step(steps, "image name") or _find_step(steps, "image tag")
        assert image_step is not None, "No image name/tag step found"

        run_script = image_step.get("run", "")
        assert "cache_ref=" in run_script, "Image step must emit a cache_ref output"
        assert "${GITHUB_REPOSITORY,,}:buildcache" in run_script, (
            "Cache ref must use a stable lowercased ghcr buildcache tag"
        )

    def test_docker_build_uses_registry_cache_backend(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Docker build step must use registry-backed cache import/export."""
        steps = _get_steps(deploy_workflow)
        build = _find_step(steps, "build and push")
        assert build is not None

        with_block = build.get("with", {})
        cache_from = str(with_block.get("cache-from", ""))
        cache_to = str(with_block.get("cache-to", ""))

        assert cache_from == "type=registry,ref=${{ steps.image.outputs.cache_ref }}"
        assert cache_to == "type=registry,ref=${{ steps.image.outputs.cache_ref }},mode=max"

    def test_docker_build_revision_label_uses_resolved_source_sha(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """OCI revision label must match the resolved source SHA, not the event SHA blindly."""
        steps = _get_steps(deploy_workflow)
        build = _find_step(steps, "build and push")
        assert build is not None

        labels = str(build.get("with", {}).get("labels", ""))
        assert "org.opencontainers.image.revision=${{ steps.image.outputs.source_sha }}" in labels

    def test_base_image_resolution_has_manifest_fallback(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Resolve base images must fall back when geo-base-stable is unavailable."""
        steps = _get_steps(deploy_workflow)
        resolve = _find_step(steps, "resolve base image inputs")
        assert resolve is not None, "No base image resolution step found"

        run_script = str(resolve.get("run", ""))
        assert "docker manifest inspect" in run_script, (
            "Base image resolution must verify image existence before use"
        )
        assert "falling back to" in run_script, (
            "Base image resolution must provide fallback behavior when geo-base is missing"
        )
        assert "mcr.microsoft.com/azure-functions/python:4-python3.12" in run_script

    def test_smoke_runtime_status_normalized(self, deploy_workflow: dict[str, Any]) -> None:
        """Smoke checks must normalize enum-style runtime statuses from diagnostics APIs."""
        steps = _get_steps(deploy_workflow)
        smoke = _find_step(steps, "post-deploy smoke checks")
        assert smoke is not None, "No post-deploy smoke checks step found"

        run_script = str(smoke.get("run", ""))
        assert "normalize_runtime_status" in run_script, (
            "Smoke checks must normalize runtime status strings before comparisons"
        )
        assert 'endswith("Completed")' in run_script, (
            "Smoke checks must accept enum-style completed values from Durable APIs"
        )

    def test_no_functions_action(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must NOT use azure/functions-action (code deploy)."""
        steps = _get_steps(deploy_workflow)
        for step in steps:
            uses = step.get("uses", "")
            assert "azure/functions-action" not in uses or "container" in uses, (
                "Must not use azure/functions-action — container deployment "
                "uses docker/build-push-action + az functionapp config container set"
            )

    def test_packages_write_permission(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must have packages:write permission for ghcr.io push."""
        permissions = deploy_workflow.get("permissions", {})
        assert permissions.get("packages") == "write", (
            "Workflow must have 'packages: write' permission to push to ghcr.io"
        )

    def test_dockerfile_in_trigger_paths(self, deploy_workflow: dict[str, Any]) -> None:
        """Dockerfile changes must trigger a deployment."""
        # PyYAML 1.1 parses bare `on:` as boolean True
        workflow_any = cast("dict[Any, Any]", deploy_workflow)
        on_block = workflow_any.get("on") or workflow_any.get(True, {})
        paths = on_block.get("push", {}).get("paths", [])
        assert "Dockerfile" in paths, (
            "Dockerfile must be in the trigger paths so image changes trigger deploy"
        )


# ---------------------------------------------------------------------------
# Test: Function readiness check before Event Grid subscription
# ---------------------------------------------------------------------------


class TestReadinessCheck:
    """Verify the workflow enforces strict runtime contract before Event Grid reconciliation."""

    def test_reconcile_step_exists(self, deploy_workflow: dict[str, Any]) -> None:
        """Workflow must have a reconciliation step that validates runtime readiness."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None, (
            "No reconciliation step found — the workflow must verify "
            "function readiness and reconcile Event Grid before proceeding"
        )

    def test_reconcile_uses_host_status_endpoint(self, deploy_workflow: dict[str, Any]) -> None:
        """Reconciliation must poll authenticated host-status endpoint."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")
        assert "curl" in run_script and "/admin/host/status" in run_script, (
            "Reconciliation must call /admin/host/status for authoritative host state"
        )
        assert "/admin/functions" in run_script, (
            "Reconciliation must call /admin/functions to verify trigger registration"
        )
        assert "x-functions-key" in run_script, "Reconciliation must authenticate with host key"
        assert "listKeys" in run_script, "Reconciliation must fetch host keys via listKeys"

    def test_reconcile_checks_running_state(self, deploy_workflow: dict[str, Any]) -> None:
        """Reconciliation must gate on host state=Running."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")
        assert "state" in run_script and "Running" in run_script, (
            "Reconciliation must evaluate host state and require Running"
        )

    def test_reconcile_has_retry_loop(self, deploy_workflow: dict[str, Any]) -> None:
        """Reconciliation must retry (not just check once)."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")
        has_loop = "for " in run_script or "while " in run_script
        has_sleep = "sleep" in run_script
        assert has_loop and has_sleep, "Reconciliation must include a retry loop with sleep"

    def test_reconcile_hard_fail_on_contract_violation(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Reconciliation must hard-fail when runtime contract is not met."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")
        # Check for failing exit code on violation (exit 1)
        assert "fail()" in run_script or "exit 1" in run_script, (
            "Reconciliation must hard-fail if runtime contract cannot be met"
        )

    def test_reconcile_uses_cli_commands(self, deploy_workflow: dict[str, Any]) -> None:
        """Event Grid subscription must be created via Azure CLI."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None, "Reconciliation step not found"
        run_script = reconcile.get("run", "")
        assert "az eventgrid system-topic event-subscription" in run_script, (
            "Reconciliation must use Azure CLI for Event Grid operations"
        )
        assert "SUBSCRIPTION_NAME" in run_script or "evgs-kml-upload" in run_script, (
            "Event Grid subscription must reference the subscription name variable or constant"
        )

    def test_reconcile_includes_subscription_verification(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Reconciliation must verify the subscription endpoint URL matches runtime."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")
        assert "endpoint" in run_script, "Reconciliation must verify subscription endpoint URL"
        assert "properties" in run_script, "Reconciliation must check subscription properties"

    def test_reconcile_deletes_drifted_subscription_non_interactively(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Drift cleanup must not prompt for confirmation on headless CI runners."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")

        assert "event-subscription delete" in run_script, (
            "Reconciliation must delete drifted Event Grid subscriptions before recreate"
        )
        assert "--yes" in run_script, (
            "Drift cleanup must pass --yes so Azure CLI does not prompt in CI"
        )
        assert "Deletion has not propagated yet" in run_script, (
            "Drift cleanup should wait for the old subscription to disappear before recreate"
        )
        assert "DELETE_PROPAGATION_SECONDS" in run_script, (
            "Delete propagation should use a dedicated timeout budget, not one poll interval"
        )
        assert (
            "Existing subscription delete did not propagate within retry budget." in run_script
        ), "Delete propagation should fail clearly if the old subscription never disappears"

    def test_reconcile_retries_endpoint_mismatch_before_failing(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Recreate verification must tolerate stale endpoint reads until convergence."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")

        assert "Event Grid subscription destination has not converged yet" in run_script, (
            "Reconciliation should log endpoint mismatch as a retryable convergence state"
        )
        assert "sleep 5" in run_script, (
            "Endpoint mismatch verification should wait and retry instead of failing immediately"
        )
        assert (
            'fail "Event Grid subscription exists but points at an unexpected endpoint."'
            not in run_script
        ), (
            "Transient endpoint mismatch during recreate verification should not hard-fail immediately"
        )
        assert 'LAST_CREATE_ERROR="Endpoint mismatch during reconcile:' in run_script, (
            "Endpoint mismatch should record actionable diagnostics for timeout failures"
        )
        assert "current_endpoint=${CURRENT_ENDPOINT:-none}" in run_script, (
            "Endpoint mismatch diagnostics should include the last observed endpoint"
        )
        assert "Azure did not return destination resource details after recreate" in run_script, (
            "Recreated subscriptions should tolerate missing destination details when Azure omits them"
        )
        assert "DELETE_CONFIRMED" in run_script, (
            "Accepting endpoint-less subscriptions should only happen after confirmed delete and recreate"
        )
        assert (
            "Final verification accepted state=Succeeded without destination details after confirmed recreate."
            in run_script
        ), (
            "Final verification should honor the same endpoint-less success path after confirmed recreate"
        )

    def test_reconcile_inner_verify_loop_respects_outer_deadline(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """The inner verification loop must not run past the overall reconcile timeout."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")

        assert "if (( $(date +%s) >= RECONCILE_DEADLINE )); then" in run_script, (
            "Inner verification should stop when the outer reconcile deadline is reached"
        )

    def test_reconcile_uses_azure_function_destination_connector(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Reconciliation must create Event Grid subscription via Azure Function endpoint type."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")

        assert "--endpoint-type azurefunction" in run_script, (
            "Reconciliation must use Event Grid azurefunction endpoint type"
        )
        assert "/functions/${TRIGGER_NAME}" in run_script, (
            "Reconciliation must target the Function child resource ID"
        )
        assert "--endpoint-type webhook" not in run_script, (
            "Webhook destination should not be used for Function App subscription reconcile"
        )
        assert "runtime/webhooks/eventgrid" not in run_script, (
            "Reconciliation should not depend on runtime webhook URL wiring"
        )

    def test_reconcile_restarts_once_on_running_but_unindexed_timeout(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Reconciliation should self-heal when host is Running but trigger index is empty."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = str(reconcile.get("run", ""))

        assert "probe_runtime_readiness_until" in run_script, (
            "Reconciliation should centralize readiness probing for reuse across retry windows"
        )
        assert "host running but trigger unindexed" in run_script.lower(), (
            "Reconciliation should detect and log the specific running-but-unindexed failure mode"
        )
        assert "az functionapp restart" in run_script, (
            "Reconciliation should restart the Function App once before hard failing"
        )
        assert "RESTART_READY_SECONDS=300" in run_script, (
            "Restart recovery window should be explicitly bounded"
        )
        assert "RESTART_READINESS_DEADLINE" in run_script, (
            "Restart path should reuse deadline-bound readiness verification"
        )

    def test_reconcile_does_not_require_webhook_validation_probe(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Azure Function destination should avoid explicit webhook handshake probe logic."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = str(reconcile.get("run", ""))

        assert "probe_eventgrid_webhook_until" not in run_script, (
            "Reconciliation should no longer implement manual webhook handshake probes"
        )
        assert "aeg-event-type: SubscriptionValidation" not in run_script, (
            "Subscription validation emulation is unnecessary with azurefunction destination"
        )
        assert "Event Grid webhook endpoint did not become validation-ready" not in run_script, (
            "Webhook-specific failure mode should not be present after connector migration"
        )

    def test_reconcile_uses_reactive_retry_delay_for_subscription_create(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Retry cadence should be state-driven instead of a flat static sleep between create attempts."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = str(reconcile.get("run", ""))

        assert 'retry_delay="$SUBSCRIPTION_POLL_INTERVAL_SECONDS"' in run_script
        assert "Retrying in ${retry_delay}s..." in run_script
        assert "if (( retry_delay < 30 )); then" in run_script
        assert "retry_delay=$((retry_delay + 5))" in run_script

    def test_reconcile_has_wall_clock_timeout(self, deploy_workflow: dict[str, Any]) -> None:
        """Reconciliation must have wall-clock timeout, not just attempt count."""
        steps = _get_steps(deploy_workflow)
        reconcile = _find_step(steps, "reconcile")
        assert reconcile is not None
        run_script = reconcile.get("run", "")

        # Must track elapsed time (variable names may vary: ELAPSED, elapsed, SECONDS, etc.)
        has_elapsed = any(x in run_script for x in ["ELAPSED", "SECONDS", "seconds", "elapsed"])
        assert has_elapsed, "Reconciliation must track elapsed time"

        # Must have max duration (variable naming may vary: MAX_DURATION, MAX_*_SECONDS, etc.)
        has_max = any(x in run_script for x in ["MAX_", "max_", "timeout"])
        assert has_max, "Reconciliation must have timeout bounds"

    def test_fast_strategy_has_adaptive_admin_probe_fallback(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Fast strategy must pivot to authenticated admin probes on prolonged 404 warmup."""
        steps = _get_steps(deploy_workflow)
        fast = _find_step(steps, "verify runtime readiness (fast strategy)")
        assert fast is not None, "Fast readiness step not found"

        run_script = str(fast.get("run", ""))
        assert "host/default/listKeys" in run_script, (
            "Fast strategy must resolve host keys for adaptive fallback probes"
        )
        assert "/admin/host/status" in run_script, (
            "Fast strategy fallback must probe authenticated host status"
        )
        assert "/admin/functions" in run_script, (
            "Fast strategy fallback must verify trigger indexing via /admin/functions"
        )
        assert "kml_blob_trigger" in run_script or "EVENT_GRID_TRIGGER_FUNCTION" in run_script, (
            "Fast strategy fallback must verify Event Grid trigger registration"
        )

    def test_fast_strategy_tracks_404_only_window_before_failing(
        self, deploy_workflow: dict[str, Any]
    ) -> None:
        """Fast strategy should treat sustained 404 startup as a recoverable warmup signal."""
        steps = _get_steps(deploy_workflow)
        fast = _find_step(steps, "verify runtime readiness (fast strategy)")
        assert fast is not None, "Fast readiness step not found"

        run_script = str(fast.get("run", ""))
        assert "health=404" not in run_script, (
            "Guard: script should use code variables, not hardcoded logs"
        )
        assert "health_code" in run_script and "readiness_code" in run_script
        assert "404" in run_script, "Fast strategy should branch on 404 startup responses"
        assert "Fast strategy adaptive fallback" in run_script, (
            "Fast strategy should emit a clear adaptive fallback log marker"
        )

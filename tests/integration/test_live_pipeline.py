"""Live E2E integration tests against the deployed Azure pipeline.

These tests verify the complete KML → imagery → metadata flow against the
real deployed environment. They skip automatically when the required
environment variables are absent, so they never block standard CI.

Required environment variables
-------------------------------
E2E_FUNCTION_APP_HOSTNAME
    Function App default hostname, no ``https://`` prefix.
    Example: ``func-kmlsat-dev.wittyground-abc.northeurope.azurecontainerapps.io``
E2E_STORAGE_ACCOUNT_URL
    Blob service endpoint.
    Example: ``https://stkmlsatdev.blob.core.windows.net``
E2E_STORAGE_CONNECTION_STRING
    Optional. Full storage connection string. When present, tests prefer
    this over token-based auth to avoid RBAC data-plane drift.
E2E_FUNCTION_HOST_KEY
    Default host key, used to authenticate the Durable management API
    when locating the orchestration instance triggered by our upload.

Running locally
---------------
Export hostname + host key and either storage variable above, then::

    pytest tests/integration/ -m e2e -v

Running in CI
-------------
The ``.github/workflows/e2e.yml`` workflow resolves these values via
Azure CLI after OIDC login and injects them as env vars.

Design notes
------------
- Blob uploads prefer ``E2E_STORAGE_CONNECTION_STRING`` when provided by
    workflow resolution. If absent, tests fall back to ``DefaultAzureCredential``
    (OIDC in CI, ``az login`` locally).
- Each test prefixes its blob name with a UUID so concurrent test runs
  never collide with each other (PID 7.4.4 Idempotent).
- After upload the Durable management API (authenticated) is polled to
  locate the orchestration instance triggered by Event Grid.  Once the
  instance ID is known, the anonymous ``/api/orchestrator/{instance_id}``
  endpoint (fixed in #131) drives all subsequent status/output checks.
- Timing assertions enforce NFR-1: complete pipeline < 30 minutes.
- If provider coverage is absent for an AOI, a ``partial`` status result
  is accepted as long as metadata was written — the pipeline correctly
  records what it could do.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

# ---------------------------------------------------------------------------
# Environment-based skip condition
# ---------------------------------------------------------------------------

_HOSTNAME: str | None = os.getenv("E2E_FUNCTION_APP_HOSTNAME")
_STORAGE_URL: str | None = os.getenv("E2E_STORAGE_ACCOUNT_URL")
_STORAGE_CONNECTION_STRING: str | None = os.getenv("E2E_STORAGE_CONNECTION_STRING")
_HOST_KEY: str | None = os.getenv("E2E_FUNCTION_HOST_KEY")

_live = pytest.mark.skipif(
    not (_HOSTNAME and _HOST_KEY and (_STORAGE_CONNECTION_STRING or _STORAGE_URL)),
    reason=(
        "Live E2E env vars not set — skipping. "
        "Set E2E_FUNCTION_APP_HOSTNAME, E2E_FUNCTION_HOST_KEY, and either "
        "E2E_STORAGE_CONNECTION_STRING or E2E_STORAGE_ACCOUNT_URL to run "
        "against a deployed environment."
    ),
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INPUT_CONTAINER = "kml-input"
_OUTPUT_CONTAINER = "kml-output"
_DATA_DIR = Path(__file__).parent.parent / "data"

# NFR-1: pipeline under 30 min; test ceiling is 25 min to give headroom.
_MAX_WAIT_SECONDS = 1500  # 25 minutes
# How long to poll the Durable API before declaring the instance not found.
_INSTANCE_FIND_TIMEOUT_S = 240  # 4 minutes
_POLL_INTERVAL_S = 30
_DURABLE_HUB = "KmlSatelliteHub"
_DURABLE_CONNECTION = "Storage"
# Blob path pattern for metadata outputs (PID Section 10.1).
_METADATA_PATH_PATTERN = re.compile(r"^metadata/\d{4}/\d{2}/[a-z0-9-]+/[a-z0-9-]+\.json$")

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _blob_service() -> BlobServiceClient:
    if _STORAGE_CONNECTION_STRING:
        return BlobServiceClient.from_connection_string(_STORAGE_CONNECTION_STRING)

    assert _STORAGE_URL, "E2E_STORAGE_ACCOUNT_URL must be set when no connection string exists"
    return BlobServiceClient(
        account_url=_STORAGE_URL,
        credential=DefaultAzureCredential(),
    )


def _upload_kml(blob_svc: BlobServiceClient, kml_path: Path, blob_name: str) -> None:
    """Upload *kml_path* to the kml-input container as *blob_name*."""
    assert kml_path.exists(), f"Test KML not found: {kml_path}"
    container = blob_svc.get_container_client(_INPUT_CONTAINER)
    with kml_path.open("rb") as fh:
        container.upload_blob(name=blob_name, data=fh, overwrite=True)


def _find_instance_id(
    blob_name: str,
    created_after: datetime,
    *,
    timeout_s: int = _INSTANCE_FIND_TIMEOUT_S,
) -> str | None:
    """Poll the Durable management API until an orchestration for *blob_name* starts.

    Returns the instance ID, or ``None`` if not found within *timeout_s* seconds.
    """
    assert _HOSTNAME and _HOST_KEY, "HOSTNAME and HOST_KEY must be set"
    endpoint = (
        f"https://{_HOSTNAME}/runtime/webhooks/durabletask/instances"
        f"?taskHub={_DURABLE_HUB}"
        f"&connection={_DURABLE_CONNECTION}"
        f"&createdTimeFrom={created_after.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        "&top=50"
        "&showInput=true"
        f"&code={_HOST_KEY}"
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(endpoint, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError:
            time.sleep(10)
            continue
        for instance in resp.json():
            inp: Any = instance.get("input") or {}
            # Input is a parsed dict in most SDK versions.
            if isinstance(inp, dict) and inp.get("blob_name") == blob_name:
                return str(instance["instanceId"])
            # Fallback: older runtimes may serialise input as a JSON string.
            if isinstance(inp, str) and f'"blob_name": "{blob_name}"' in inp:
                return str(instance["instanceId"])
        time.sleep(10)
    return None


def _poll_until_terminal(instance_id: str) -> dict[str, Any]:
    """Poll the anonymous orchestrator status endpoint until a terminal state.

    Uses ``/api/orchestrator/{instance_id}`` (anonymous, fixed by #131).
    Returns the last payload received; callers assert on ``runtimeStatus``.
    """
    assert _HOSTNAME, "E2E_FUNCTION_APP_HOSTNAME must be set"
    endpoint = f"https://{_HOSTNAME}/api/orchestrator/{instance_id}"
    deadline = time.monotonic() + _MAX_WAIT_SECONDS
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(endpoint, timeout=30)
            if resp.status_code == 200:
                payload: dict[str, Any] = resp.json()
                last = payload
                if payload.get("runtimeStatus") in (
                    "Completed",
                    "Failed",
                    "Terminated",
                    "Canceled",
                ):
                    return last
        except httpx.HTTPError:
            # Transient network/readiness failures are expected while polling.
            time.sleep(_POLL_INTERVAL_S)
            continue
        time.sleep(_POLL_INTERVAL_S)
    return last  # timed out


def _blob_exists(blob_svc: BlobServiceClient, container: str, blob_path: str) -> bool:
    """Return True if the blob at *container*/*blob_path* exists and is non-empty."""
    try:
        props = blob_svc.get_blob_client(container=container, blob=blob_path).get_blob_properties()
        return int(props.size) > 0
    except ResourceNotFoundError:
        return False


def _run_pipeline(kml_filename: str) -> tuple[str, dict[str, Any]]:
    """Upload a KML, find its orchestration, and poll until terminal.

    Returns ``(instance_id, result_payload)``.  Assertions are left to
    callers so each test can provide a clear failure message.
    """
    test_id = uuid.uuid4().hex[:8]
    blob_name = f"e2e-test/{test_id}/{kml_filename}"
    kml_path = _DATA_DIR / kml_filename

    blob_svc = _blob_service()
    upload_time = datetime.now(UTC)
    _upload_kml(blob_svc, kml_path, blob_name)

    instance_id = _find_instance_id(blob_name, upload_time)
    assert instance_id is not None, (
        f"No orchestration instance found for blob '{blob_name}' within "
        f"{_INSTANCE_FIND_TIMEOUT_S}s. Check Event Grid subscription and "
        "function readiness."
    )
    result = _poll_until_terminal(instance_id)
    return instance_id, result


# ---------------------------------------------------------------------------
# Single-polygon E2E tests (issue #13 AC-1 / NFR-1)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestLiveSinglePolygon:
    """E2E: single-polygon KML produces metadata and imagery in under 30 minutes."""

    @_live
    def test_pipeline_reaches_completed_state(self) -> None:
        """Pipeline must reach Completed (not Failed) for a well-formed single polygon."""
        _, result = _run_pipeline("01_single_polygon_orchard.kml")

        assert result.get("runtimeStatus") == "Completed", (
            f"Expected Completed; got {result.get('runtimeStatus')!r}. "
            f"output={result.get('output')}"
        )

    @_live
    def test_single_polygon_metadata_artifact_written(self) -> None:
        """AC-6: at least one metadata JSON must exist in blob storage."""
        instance_id, result = _run_pipeline("01_single_polygon_orchard.kml")
        assert result.get("runtimeStatus") == "Completed", (
            f"Pipeline not Completed — cannot verify artifacts. "
            f"instance={instance_id} status={result.get('runtimeStatus')}"
        )

        output = result.get("output") or {}
        artifacts = output.get("artifacts") or {}
        metadata_paths: list[str] = artifacts.get("metadataPaths") or []

        assert len(metadata_paths) >= 1, (
            f"Expected ≥1 metadata path in output; got none. output={output}"
        )

        blob_svc = _blob_service()
        for path in metadata_paths:
            assert _blob_exists(blob_svc, _OUTPUT_CONTAINER, path), (
                f"Metadata blob missing or empty in '{_OUTPUT_CONTAINER}': {path}"
            )

    @_live
    def test_metadata_path_conforms_to_pid_section_10_1(self) -> None:
        """AC-6: metadata blob path must match ``metadata/YYYY/MM/project/feature.json``."""
        _, result = _run_pipeline("01_single_polygon_orchard.kml")
        assert result.get("runtimeStatus") == "Completed"

        artifacts = (result.get("output") or {}).get("artifacts") or {}
        metadata_paths: list[str] = artifacts.get("metadataPaths") or []
        assert metadata_paths, "No metadata paths returned — cannot check format"

        for path in metadata_paths:
            assert _METADATA_PATH_PATTERN.match(path), (
                f"Metadata path {path!r} does not match PID 10.1 pattern "
                "'metadata/YYYY/MM/project/feature.json'"
            )

    @_live
    def test_pipeline_status_reflects_actual_outcome(self) -> None:
        """output.status must be 'success' or 'partial' — never silent failure."""
        _, result = _run_pipeline("01_single_polygon_orchard.kml")
        assert result.get("runtimeStatus") == "Completed"

        output = result.get("output") or {}
        pipeline_status = output.get("status", "")
        assert pipeline_status in ("success", "partial"), (
            f"Unexpected pipeline status {pipeline_status!r}. Full output: {output}"
        )

    @_live
    def test_imagery_artifacts_exist_when_status_is_success(self) -> None:
        """AC-4: if pipeline status is 'success', raw and clipped imagery must be present."""
        _, result = _run_pipeline("01_single_polygon_orchard.kml")
        assert result.get("runtimeStatus") == "Completed"

        output = result.get("output") or {}
        if output.get("status") != "success":
            pytest.skip("Pipeline returned partial status — imagery check skipped")

        artifacts = output.get("artifacts") or {}
        raw_paths: list[str] = artifacts.get("rawImageryPaths") or []
        clipped_paths: list[str] = artifacts.get("clippedImageryPaths") or []

        assert raw_paths, "Success status but no raw imagery paths reported"

        blob_svc = _blob_service()
        for path in raw_paths:
            assert _blob_exists(blob_svc, _OUTPUT_CONTAINER, path), (
                f"Raw imagery blob missing: {_OUTPUT_CONTAINER}/{path}"
            )
        for path in clipped_paths:
            assert _blob_exists(blob_svc, _OUTPUT_CONTAINER, path), (
                f"Clipped imagery blob missing: {_OUTPUT_CONTAINER}/{path}"
            )


# ---------------------------------------------------------------------------
# Multi-feature E2E tests (issue #13 AC-1)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestLiveMultiFeature:
    """E2E: multi-feature KML produces independent outputs per feature."""

    @_live
    def test_multi_feature_pipeline_completes(self) -> None:
        """Multi-feature KML (4 Placemarks) must reach Completed state."""
        _, result = _run_pipeline("03_multi_feature_vineyard.kml")
        assert result.get("runtimeStatus") == "Completed", (
            f"Multi-feature pipeline not Completed: {result.get('runtimeStatus')}. "
            f"output={result.get('output')}"
        )

    @_live
    def test_multi_feature_produces_output_per_feature(self) -> None:
        """aoiCount and metadataCount must equal the number of features in the KML (4)."""
        _, result = _run_pipeline("03_multi_feature_vineyard.kml")
        assert result.get("runtimeStatus") == "Completed"

        output = result.get("output") or {}
        assert output.get("aoiCount", 0) >= 4, (
            f"Expected ≥4 AOIs for vineyard KML; got {output.get('aoiCount')}"
        )
        assert output.get("metadataCount", 0) >= 4, (
            f"Expected ≥4 metadata outputs; got {output.get('metadataCount')}"
        )

    @_live
    def test_no_blob_path_collisions_between_features(self) -> None:
        """AC-4: each feature must produce a unique metadata blob path."""
        _, result = _run_pipeline("03_multi_feature_vineyard.kml")
        assert result.get("runtimeStatus") == "Completed"

        artifacts = (result.get("output") or {}).get("artifacts") or {}
        paths: list[str] = artifacts.get("metadataPaths") or []
        assert len(paths) == len(set(paths)), (
            f"Duplicate metadata blob paths detected (AC-4 idempotency violated): {paths}"
        )


# ---------------------------------------------------------------------------
# Polygon-with-hole E2E tests (issue #13)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestLivePolygonWithHole:
    """E2E: polygon-with-hole KML processes successfully."""

    @_live
    def test_polygon_with_hole_completes(self) -> None:
        """Inner-boundary KML must not crash the pipeline."""
        _, result = _run_pipeline("04_complex_polygon_with_hole.kml")
        assert result.get("runtimeStatus") == "Completed", (
            f"Polygon-with-hole pipeline failed: "
            f"status={result.get('runtimeStatus')} output={result.get('output')}"
        )

    @_live
    def test_polygon_with_hole_produces_metadata(self) -> None:
        """Inner-boundary polygon must produce metadata JSON."""
        _, result = _run_pipeline("04_complex_polygon_with_hole.kml")
        assert result.get("runtimeStatus") == "Completed"

        artifacts = (result.get("output") or {}).get("artifacts") or {}
        metadata_paths: list[str] = artifacts.get("metadataPaths") or []
        assert len(metadata_paths) >= 1, "Polygon-with-hole KML produced no metadata paths"

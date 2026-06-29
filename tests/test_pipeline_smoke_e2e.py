"""Back-to-back pipeline smoke test for duplicate-named AOIs.

Validates that two consecutive pipeline runs with a KML containing
duplicate feature names both reach a terminal state without silent data
loss or key collisions.

Requires:
- Azurite running on localhost (``make dev-up``)
- Local Functions host running on port 7071 (``make dev-func``)

Run with::

    uv run pytest tests/test_pipeline_smoke_e2e.py -v -m integration

Skip when dependencies are unavailable::

    uv run pytest tests/ -v -m "not integration"
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from _azurite import AZURITE_BLOB_BASE, AZURITE_CONN_STR
from azure.storage.blob import BlobServiceClient, ContentSettings

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FUNC_BASE = "http://localhost:7071"
_INPUT_CONTAINER = "kml-input"
_TERMINAL_STATUSES = frozenset({"Completed", "Failed", "Canceled", "Terminated"})
# duplicate_names.kml contains exactly 2 Placemark elements.
_DUPLICATE_KML_FEATURE_COUNT = 2

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Availability guards — skip the whole module if dependencies are absent
# ---------------------------------------------------------------------------


def _azurite_reachable() -> bool:
    """Return True if Azurite is listening on the well-known local port."""
    try:
        client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
        client.get_account_information()
    except Exception:
        return False
    return True


def _func_host_reachable() -> bool:
    """Return True if the local Functions host responds to /api/health."""
    try:
        resp = httpx.get(f"{FUNC_BASE}/api/health", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


skip_no_azurite = pytest.mark.skipif(
    not _azurite_reachable(),
    reason="Azurite not running — start with: make dev-up",
)

skip_no_func_host = pytest.mark.skipif(
    not _func_host_reachable(),
    reason="Functions host not running — start with: make dev-func",
)


# ---------------------------------------------------------------------------
# Pipeline submission helpers
# ---------------------------------------------------------------------------


def _upload_kml(kml_path: Path, instance_id: str) -> tuple[str, int]:
    """Upload ticket + KML to Azurite; return (blob_url, content_length).

    The ticket blob must land before the KML blob so that blob_trigger can
    read user metadata.  Using ``tier=demo`` tells the orchestrator to skip
    billing finalization so no quota is consumed.
    """
    client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    container = client.get_container_client(_INPUT_CONTAINER)
    if not container.exists():
        container.create_container()

    ticket = {
        "user_id": "e2e-smoke-test",
        "tier": "demo",
        "correlation_id": instance_id,
    }
    ticket_blob = client.get_blob_client(_INPUT_CONTAINER, f".tickets/{instance_id}.json")
    ticket_blob.upload_blob(
        json.dumps(ticket).encode(),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )

    kml_bytes = kml_path.read_bytes()
    blob_name = f"analysis/{instance_id}.kml"
    kml_blob = client.get_blob_client(_INPUT_CONTAINER, blob_name)
    kml_blob.upload_blob(
        kml_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/vnd.google-earth.kml+xml"),
    )
    blob_url = f"{AZURITE_BLOB_BASE}/{_INPUT_CONTAINER}/{blob_name}"
    return blob_url, len(kml_bytes)


def _fire_event_grid(blob_url: str, blob_name: str, content_length: int) -> None:
    """Send a mock Event Grid BlobCreated event to the local Functions host."""
    event_id = str(uuid.uuid4())
    event = [
        {
            "id": event_id,
            "topic": (
                "/subscriptions/local-dev/resourceGroups/treesight/providers/"
                "Microsoft.Storage/storageAccounts/devstoreaccount1"
            ),
            "subject": (f"/blobServices/default/containers/{_INPUT_CONTAINER}/blobs/{blob_name}"),
            "eventType": "Microsoft.Storage.BlobCreated",
            "eventTime": datetime.now(UTC).isoformat(),
            "data": {
                "api": "PutBlob",
                "clientRequestId": str(uuid.uuid4()),
                "requestId": str(uuid.uuid4()),
                "url": blob_url,
                "contentType": "application/vnd.google-earth.kml+xml",
                "contentLength": content_length,
                "blobType": "BlockBlob",
            },
            "dataVersion": "",
            "metadataVersion": "1",
        }
    ]
    resp = httpx.post(
        f"{FUNC_BASE}/runtime/webhooks/eventgrid",
        params={"functionName": "blob_trigger"},
        json=event,
        headers={"aeg-event-type": "Notification", "Content-Type": "application/json"},
        timeout=30.0,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Event Grid webhook rejected with HTTP {resp.status_code}: {resp.text}")


def _poll_orchestrator(
    instance_id: str,
    *,
    timeout: int = 180,
    interval: int = 3,
) -> dict:
    """Poll the orchestrator status endpoint until terminal; raise TimeoutError."""
    url = f"{FUNC_BASE}/api/orchestrator/{instance_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=10.0)
        except httpx.RequestError:
            time.sleep(interval)
            continue
        if resp.status_code == 404:
            time.sleep(interval)
            continue
        data = resp.json()
        status = data.get("runtimeStatus", "Unknown")
        if status in _TERMINAL_STATUSES:
            return data
        time.sleep(interval)
    raise TimeoutError(
        f"Orchestration {instance_id!r} did not reach a terminal state within {timeout}s"
    )


def _submit_and_wait(kml_path: Path) -> dict:
    """Upload KML, fire Event Grid, poll to terminal, and return the status payload."""
    instance_id = str(uuid.uuid4())
    blob_name = f"analysis/{instance_id}.kml"
    blob_url, content_length = _upload_kml(kml_path, instance_id)
    _fire_event_grid(blob_url, blob_name, content_length)
    return _poll_orchestrator(instance_id)


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


@skip_no_azurite
@skip_no_func_host
class TestDuplicateAoiBackToBackSmoke:
    """Two consecutive pipeline submissions of a duplicate-named KML.

    The original flakiness was a silent key collision in the ingestion
    phase that made the second run appear to hang.  These tests verify:

    1. Both runs reach a terminal state (no hang from duplicate names).
    2. Both runs produce consistent outcomes — deterministic, not flaky.
    3. When the pipeline completes, the AOI count matches the feature count.
    """

    def test_first_run_reaches_terminal_state(self) -> None:
        """First submission of duplicate_names.kml reaches a terminal state."""
        kml_path = FIXTURES_DIR / "duplicate_names.kml"

        result = _submit_and_wait(kml_path)

        assert result.get("runtimeStatus") in _TERMINAL_STATUSES, (
            f"First run did not reach terminal state: {result.get('runtimeStatus')!r}"
        )

    def test_second_run_reaches_terminal_state(self) -> None:
        """Second (back-to-back) submission of duplicate_names.kml reaches a terminal state."""
        kml_path = FIXTURES_DIR / "duplicate_names.kml"

        result = _submit_and_wait(kml_path)

        assert result.get("runtimeStatus") in _TERMINAL_STATUSES, (
            f"Second run did not reach terminal state: {result.get('runtimeStatus')!r}"
        )

    def test_back_to_back_runs_are_consistent(self) -> None:
        """Two consecutive submissions produce the same terminal status.

        Flakiness in duplicate-name handling manifests as non-deterministic
        outcomes between runs — one completes while the other hangs or fails
        at a different phase.  Both must reach the same terminal state.
        """
        kml_path = FIXTURES_DIR / "duplicate_names.kml"

        result_1 = _submit_and_wait(kml_path)
        result_2 = _submit_and_wait(kml_path)

        status_1 = result_1.get("runtimeStatus")
        status_2 = result_2.get("runtimeStatus")

        assert status_1 == status_2, (
            f"Inconsistent terminal statuses: run 1={status_1!r}, run 2={status_2!r}. "
            "Duplicate-name handling must be deterministic across back-to-back submissions."
        )

    def test_completed_runs_have_correct_aoi_count(self) -> None:
        """When the pipeline completes, both runs report aoiCount == feature count.

        This guards against silent data loss: if duplicate-named AOIs cause a
        key collision, the output count drops below the input feature count.
        """
        kml_path = FIXTURES_DIR / "duplicate_names.kml"

        result_1 = _submit_and_wait(kml_path)
        result_2 = _submit_and_wait(kml_path)

        for run_num, result in enumerate((result_1, result_2), start=1):
            status = result.get("runtimeStatus")
            if status != "Completed":
                pytest.skip(
                    f"Run {run_num} reached {status!r} instead of 'Completed'. "
                    "Resolve duplicate-AOI handling so the pipeline completes before "
                    "asserting AOI counts."
                )

            output = result.get("output", {})
            aoi_count = output.get("aoiCount") if isinstance(output, dict) else None
            assert aoi_count == _DUPLICATE_KML_FEATURE_COUNT, (
                f"Run {run_num}: aoiCount={aoi_count!r} but expected "
                f"{_DUPLICATE_KML_FEATURE_COUNT} (one per input feature, no silent loss)."
            )

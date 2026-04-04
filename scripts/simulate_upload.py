"""Upload a KML file to Azurite and trigger the pipeline via a mock Event Grid event.

Usage:
  uv run python scripts/simulate_upload.py                      # uses tests/fixtures/sample.kml
  uv run python scripts/simulate_upload.py path/to/custom.kml   # custom KML file
  uv run python scripts/simulate_upload.py --container demo-input  # custom container
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from _azurite import AZURITE_BLOB_BASE, AZURITE_CONN_STR
from azure.storage.blob import BlobServiceClient, ContentSettings

FUNC_BASE = "http://localhost:7071"
DEFAULT_KML = "tests/fixtures/sample.kml"
DEFAULT_CONTAINER = "kml-input"
DEFAULT_EVENT_GRID_FUNCTION_NAME = "blob_trigger"


def upload_kml(kml_path: Path, container: str) -> tuple[str, str, int]:
    """Upload KML to Azurite and return (blob_name, blob_url, content_length)."""
    client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)

    container_client = client.get_container_client(container)
    if not container_client.exists():
        container_client.create_container()
        print(f"  Created container '{container}'.")

    kml_bytes = kml_path.read_bytes()
    blob_name = kml_path.name
    blob_client = client.get_blob_client(container, blob_name)
    blob_client.upload_blob(
        kml_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/vnd.google-earth.kml+xml"),
    )
    blob_url = f"{AZURITE_BLOB_BASE}/{container}/{blob_name}"
    print(f"  Uploaded {kml_path} -> {blob_url} ({len(kml_bytes)} bytes)")
    return blob_name, blob_url, len(kml_bytes)


def fire_event_grid(
    blob_url: str,
    blob_name: str,
    content_length: int,
    container: str,
    provider_config: dict[str, Any] | None = None,
    function_name: str = DEFAULT_EVENT_GRID_FUNCTION_NAME,
    function_key: str | None = None,
    strict: bool = True,
) -> str:
    """Send a mock Event Grid BlobCreated event to the local func host."""
    event_id = str(uuid.uuid4())
    data: dict[str, Any] = {
        "api": "PutBlob",
        "clientRequestId": str(uuid.uuid4()),
        "requestId": str(uuid.uuid4()),
        "url": blob_url,
        "contentType": "application/vnd.google-earth.kml+xml",
        "contentLength": content_length,
        "blobType": "BlockBlob",
    }
    if provider_config:
        data["provider_config"] = provider_config

    event: list[dict[str, str | dict[str, Any]]] = [
        {
            "id": event_id,
            "topic": "/subscriptions/local-dev/resourceGroups/treesight/providers/"
            "Microsoft.Storage/storageAccounts/devstoreaccount1",
            "subject": f"/blobServices/default/containers/{container}/blobs/{blob_name}",
            "eventType": "Microsoft.Storage.BlobCreated",
            "eventTime": datetime.now(UTC).isoformat(),
            "data": data,
            "dataVersion": "",
            "metadataVersion": "1",
        }
    ]

    endpoint = httpx.URL(FUNC_BASE).join("/runtime/webhooks/eventgrid")
    query_params: dict[str, str] = {"functionName": function_name}
    if function_key:
        query_params["code"] = function_key

    if function_key:
        display_url = f"{endpoint}?functionName={function_name}&code=***REDACTED***"
    else:
        display_url = f"{endpoint}?functionName={function_name}"

    print(f"  Firing Event Grid event -> {display_url}")
    print(f"  Event ID (= orchestration instance ID): {event_id}")

    resp = httpx.post(
        str(endpoint),
        params=query_params,
        json=event,
        headers={"aeg-event-type": "Notification", "Content-Type": "application/json"},
        timeout=30.0,
    )

    if resp.status_code in (200, 202):
        print(f"  Event accepted (HTTP {resp.status_code}).")
    else:
        msg = f"Event Grid webhook rejected with HTTP {resp.status_code}: {resp.text}"
        print(f"  WARNING: {msg}")
        if strict:
            raise RuntimeError(msg)

    return event_id


def poll_orchestrator(instance_id: str, timeout: int = 120, interval: int = 3) -> None:
    """Poll the orchestrator status until complete or timeout."""
    url = f"{FUNC_BASE}/api/orchestrator/{instance_id}"
    print(f"\n  Polling orchestrator status at {url}")

    start = time.time()
    last_status = ""
    while time.time() - start < timeout:
        try:
            resp = httpx.get(url, timeout=10.0)
        except httpx.ConnectError:
            print("  ... func host not reachable, retrying")
            time.sleep(interval)
            continue

        if resp.status_code == 404:
            print("  ... orchestration not found yet, retrying")
            time.sleep(interval)
            continue

        data = resp.json()
        status = data.get("runtimeStatus", "Unknown")

        if status != last_status:
            print(f"  Status: {status}")
            last_status = status

        if status in ("Completed", "Failed", "Terminated", "Canceled"):
            print(f"\n  === Orchestration {status} ===")
            if data.get("output"):
                print(json.dumps(data["output"], indent=2, default=str))
            if data.get("customStatus"):
                print(f"  Custom status: {data['customStatus']}")
            return

        time.sleep(interval)

    print(f"  Timeout after {timeout}s — orchestration still running.")


def check_func_host() -> bool:
    """Verify the func host is reachable."""
    try:
        resp = httpx.get(f"{FUNC_BASE}/api/health", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload KML to Azurite and trigger the pipeline")
    parser.add_argument("kml_file", nargs="?", default=DEFAULT_KML, help="Path to KML file")
    parser.add_argument("--container", default=DEFAULT_CONTAINER, help="Target blob container")
    parser.add_argument("--no-poll", action="store_true", help="Skip orchestrator polling")
    parser.add_argument("--timeout", type=int, default=600, help="Polling timeout in seconds")
    parser.add_argument(
        "--event-grid-function-name",
        default=DEFAULT_EVENT_GRID_FUNCTION_NAME,
        help="Function name for Event Grid webhook (default: blob_trigger)",
    )
    parser.add_argument(
        "--event-grid-function-key",
        default=os.getenv("EVENT_GRID_FUNCTION_KEY"),
        help="Event Grid system key (or set EVENT_GRID_FUNCTION_KEY env var)",
    )
    parser.add_argument(
        "--asset-key",
        default=None,
        help="Planetary Computer asset key (e.g. visual, SCL, B04). Injected as provider_config.",
    )
    args = parser.parse_args()

    kml_path = Path(args.kml_file)
    if not kml_path.exists():
        print(f"ERROR: KML file not found: {kml_path}")
        sys.exit(1)

    print("\n=== Canopex Local Pipeline Test ===\n")

    # Step 1: Check func host
    print("[1/3] Checking func host...")
    if not check_func_host():
        print("  ERROR: Function host not reachable at localhost:7071")
        print("  Start it with: make dev-func")
        sys.exit(1)
    print("  Function host is running.")

    # Step 2: Upload KML
    print(f"\n[2/3] Uploading KML to Azurite ({args.container})...")
    blob_name, blob_url, content_length = upload_kml(kml_path, args.container)

    # Step 3: Fire Event Grid event
    print("\n[3/3] Triggering pipeline via Event Grid webhook...")
    provider_config = None
    if args.asset_key:
        provider_config = {"asset_key": args.asset_key}
        print(f"  provider_config: {provider_config}")
    instance_id = fire_event_grid(
        blob_url,
        blob_name,
        content_length,
        args.container,
        provider_config=provider_config,
        function_name=args.event_grid_function_name,
        function_key=args.event_grid_function_key,
    )

    # Step 4: Poll (optional)
    if not args.no_poll:
        print("\n=== Polling Orchestrator ===")
        poll_orchestrator(instance_id, timeout=args.timeout)
    else:
        print("\n  Skipping poll. Check manually:")
        print(f"  curl {FUNC_BASE}/api/orchestrator/{instance_id}")

    print("\nDone.")


if __name__ == "__main__":
    main()

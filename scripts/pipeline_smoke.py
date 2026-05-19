"""Upload a test KML to blob storage and verify the pipeline completes end-to-end.

Used as a CI smoke gate after deployment to confirm the parse → acquire → fulfil
pipeline works without going through the authenticated HTTP submission flow.

Usage (requires ``az login`` to be active):

  python scripts/pipeline_smoke.py \\
    --storage-account stkmlsatdevfxmh \\
    --orch-hostname func-kmlsat-dev-orch.jollysea-48e72cf8.uksouth.azurecontainerapps.io \\
    --resource-group rg-kmlsat-dev \\
    --orch-app-name func-kmlsat-dev-orch

How it works
------------
1. Generates a UUID as the instance / correlation ID.
2. Writes a minimal smoke ticket to ``.tickets/{id}.json`` in the ``kml-input``
   container (``tier=demo`` → billing finalization is skipped by the orchestrator).
3. Uploads ``tests/fixtures/sample.kml`` as ``kml-input/analysis/{id}.kml``.
   Event Grid fires ``blob_trigger`` automatically — no synthetic event needed.
4. Fetches the Durable extension system key via ``az functionapp keys list``.
5. Polls the Durable management API until the orchestration reaches a terminal state.
6. Asserts ``runtimeStatus == "Completed"`` and prints key output fields.
7. Cleans up both blobs (pass ``--no-cleanup`` to retain them for debugging).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

_TASK_HUB = "DurableFunctionsHub"
_INPUT_CONTAINER = "kml-input"
_TERMINAL_STATUSES = frozenset({"Completed", "Failed", "Canceled", "Terminated"})


def _blob_client(storage_account: str) -> BlobServiceClient:
    return BlobServiceClient(
        f"https://{storage_account}.blob.core.windows.net",
        credential=DefaultAzureCredential(),
    )


def upload_smoke_blobs(storage_account: str, instance_id: str, kml_bytes: bytes) -> None:
    """Write the smoke ticket then the KML blob to trigger the Durable pipeline.

    The ticket must land before the KML blob so the blob_trigger can read it.
    Using ``tier=demo`` makes the orchestrator skip billing finalization for
    ``user_id=ci-smoke-test``; no quota is consumed.
    """
    container = _blob_client(storage_account).get_container_client(_INPUT_CONTAINER)

    ticket: dict[str, str] = {
        "user_id": "ci-smoke-test",
        "tier": "demo",
        "correlation_id": instance_id,
    }
    container.upload_blob(
        f".tickets/{instance_id}.json",
        json.dumps(ticket).encode(),
        overwrite=True,
    )
    print(f"  uploaded ticket  .tickets/{instance_id}.json")

    # Uploading the KML last triggers Event Grid → blob_trigger → orchestrator.
    container.upload_blob(
        f"analysis/{instance_id}.kml",
        kml_bytes,
        overwrite=True,
        content_settings=ContentSettings(
            content_type="application/vnd.google-earth.kml+xml",
        ),
    )
    print(f"  uploaded KML     analysis/{instance_id}.kml")


def delete_smoke_blobs(storage_account: str, instance_id: str) -> None:
    """Best-effort cleanup — never raises; logs failures to stderr."""
    container = _blob_client(storage_account).get_container_client(_INPUT_CONTAINER)
    for name in (f".tickets/{instance_id}.json", f"analysis/{instance_id}.kml"):
        try:
            container.delete_blob(name)
            print(f"  deleted  {name}")
        except Exception as exc:
            print(f"  cleanup skipped for {name}: {exc}", file=sys.stderr)


def get_durable_key(resource_group: str, orch_app_name: str) -> str:
    """Fetch the Durable extension system key via the Azure CLI."""
    result = subprocess.run(
        [
            "az",
            "functionapp",
            "keys",
            "list",
            "--name",
            orch_app_name,
            "--resource-group",
            resource_group,
            "--query",
            "systemKeys.durabletask_extension",
            "-o",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    key = result.stdout.strip()
    if not key:
        raise RuntimeError(
            f"az functionapp keys list returned an empty Durable extension key "
            f"for {orch_app_name} in {resource_group}"
        )
    return key


def poll_orchestration(
    orch_hostname: str,
    durable_key: str,
    instance_id: str,
    *,
    max_attempts: int,
    poll_interval: int,
) -> dict:
    """Poll the Durable management API until a terminal status is reached.

    Returns the final status payload.
    Raises TimeoutError if the orchestration does not complete within
    ``max_attempts × poll_interval`` seconds.
    """
    url = (
        f"https://{orch_hostname}/runtime/webhooks/durabletask"
        f"/instances/{instance_id}"
        f"?taskHub={_TASK_HUB}&connection=Storage&code={durable_key}"
    )
    with httpx.Client(timeout=15.0) as http:
        for attempt in range(1, max_attempts + 1):
            resp = http.get(url)
            if resp.status_code == 404:
                print(f"  [{attempt}/{max_attempts}] not yet started — waiting…")
                time.sleep(poll_interval)
                continue
            resp.raise_for_status()
            payload = resp.json()
            status = payload.get("runtimeStatus", "Unknown")
            custom = payload.get("customStatus") or {}
            phase_label = (
                f" phase={custom.get('phase', '')}"
                if isinstance(custom, dict) and custom.get("phase")
                else ""
            )
            print(f"  [{attempt}/{max_attempts}] runtimeStatus={status}{phase_label}")
            if status in _TERMINAL_STATUSES:
                return payload
            time.sleep(poll_interval)
    raise TimeoutError(
        f"Pipeline did not reach a terminal state after {max_attempts} attempts "
        f"(instance_id={instance_id})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline end-to-end smoke test")
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--orch-hostname", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--orch-app-name", required=True)
    parser.add_argument("--kml-file", default="tests/fixtures/sample.kml")
    parser.add_argument("--max-attempts", type=int, default=60)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Retain smoke blobs after the test (useful for debugging failures)",
    )
    args = parser.parse_args()

    instance_id = str(uuid.uuid4())
    kml_bytes = Path(args.kml_file).read_bytes()

    print(f"Pipeline smoke test  instance_id={instance_id}")
    print(f"Uploading to {args.storage_account}…")
    upload_smoke_blobs(args.storage_account, instance_id, kml_bytes)

    print(f"Fetching Durable key for {args.orch_app_name}…")
    durable_key = get_durable_key(args.resource_group, args.orch_app_name)

    print(f"Polling {args.orch_hostname} (max {args.max_attempts} × {args.poll_interval}s)…")
    result = poll_orchestration(
        args.orch_hostname,
        durable_key,
        instance_id,
        max_attempts=args.max_attempts,
        poll_interval=args.poll_interval,
    )

    if not args.no_cleanup:
        print("Cleaning up…")
        delete_smoke_blobs(args.storage_account, instance_id)

    runtime_status = result.get("runtimeStatus")
    if runtime_status != "Completed":
        output = result.get("output")
        print(f"\n❌  Pipeline smoke test FAILED  runtimeStatus={runtime_status}", file=sys.stderr)
        if output:
            print(json.dumps(output, indent=2), file=sys.stderr)
        sys.exit(1)

    output = result.get("output", {})
    features = output.get("featureCount", "?") if isinstance(output, dict) else "?"
    aois = output.get("aoiCount", "?") if isinstance(output, dict) else "?"
    print(f"\n✅  Pipeline smoke test PASSED  features={features} aoiCount={aois}")


if __name__ == "__main__":
    main()

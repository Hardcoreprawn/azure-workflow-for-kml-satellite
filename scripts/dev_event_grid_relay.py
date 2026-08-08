"""Relay real blob uploads to the local func host as synthetic Event Grid
events (#1269 follow-up).

Azurite has no real Event Grid -- blueprints/pipeline/blob_trigger.py only
ever fires when something POSTs a matching event to its webhook (the
Event Grid trigger *is* just an HTTP webhook; there's nothing else to
emulate). scripts/simulate_upload.py already does this for one-shot test
uploads. This script does the same thing continuously: it watches the
kml-input container for new blobs -- the ones a browser uploads directly
via a SAS URL minted by blueprints/upload.py's upload_token -- and fires
the matching synthetic event for each one, so an interactive
`make dev-all` session behaves like a real deployment with a real Event
Grid subscription would.

Usage:
    uv run python scripts/dev_event_grid_relay.py
    uv run python scripts/dev_event_grid_relay.py --func-base http://func:80

Runs forever; stop with Ctrl+C (or `docker compose down` when run as the
event-grid-relay service).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from _azurite import AZURITE_BLOB_BASE, AZURITE_CONN_STR
from azure.storage.blob import BlobServiceClient
from simulate_upload import DEFAULT_CONTAINER, DEFAULT_EVENT_GRID_FUNCTION_NAME, fire_event_grid

DEFAULT_FUNC_BASE = "http://func:80"
POLL_INTERVAL_SECONDS = 2.0
_TICKET_PREFIX = ".tickets/"
_RELAYABLE_EXTENSIONS = (".kml", ".kmz")
_SECRETS_CONTAINER = "azure-webjobs-secrets"  # pragma: allowlist secret
_EVENTGRID_KEY_NAME = "eventgrid_extension"


def _is_relayable_blob(blob_name: str) -> bool:
    """True for a real KML/KMZ upload, not upload.py's .tickets/*.json ticket blob."""
    if blob_name.startswith(_TICKET_PREFIX):
        return False
    return blob_name.lower().endswith(_RELAYABLE_EXTENSIONS)


def _new_blobs(seen: set[str], current: set[str]) -> list[str]:
    """Return blobs in *current* not yet in *seen*, in a stable (sorted) order."""
    return sorted(current - seen)


def _extract_eventgrid_key(host_json_text: str) -> str | None:
    """Pull the eventgrid_extension system key out of a host.json secrets blob.

    Returns None if the key isn't present or the text isn't valid JSON —
    callers treat that as "not ready yet" and retry.
    """
    try:
        payload = json.loads(host_json_text)
    except (json.JSONDecodeError, TypeError):
        return None
    for key in payload.get("systemKeys", []):
        if key.get("name") == _EVENTGRID_KEY_NAME:
            value = key.get("value")
            return value if isinstance(value, str) else None
    return None


def _fetch_eventgrid_key(
    blob_service: BlobServiceClient, retries: int = 15, delay: float = 2.0
) -> str | None:
    """Read the func host's current Event Grid system key from Azurite.

    The Functions host auto-generates and stores this in the
    azure-webjobs-secrets blob container (in plaintext locally — there's
    no real identity to encrypt against). It's regenerated on every func
    container restart, so this is read fresh at relay startup rather than
    hardcoded — the same reasoning as scripts/pipeline_smoke.py fetching
    the equivalent key from a real deployment via `az functionapp keys
    list`, just reading the local store directly instead of the ARM API.
    """
    secrets_container = blob_service.get_container_client(_SECRETS_CONTAINER)
    for attempt in range(1, retries + 1):
        try:
            blobs = sorted(
                secrets_container.list_blobs(), key=lambda b: b.last_modified, reverse=True
            )
            for blob in blobs:
                text = secrets_container.get_blob_client(blob.name).download_blob().readall()
                key = _extract_eventgrid_key(text.decode())
                if key:
                    return key
        except Exception as exc:
            print(f"  ... could not read Event Grid system key yet ({exc})")
        if attempt < retries:
            time.sleep(delay)
    return None


def relay_forever(
    *,
    container: str = DEFAULT_CONTAINER,
    func_base: str = DEFAULT_FUNC_BASE,
    function_name: str = DEFAULT_EVENT_GRID_FUNCTION_NAME,
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> None:
    """Poll *container* forever, firing a synthetic Event Grid event for
    each new relayable blob. Never raises on a single blob's failure —
    a bad upload or a transient Azurite/func hiccup must not stop the
    relay from watching for the next one.
    """
    client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    container_client = client.get_container_client(container)

    print("Fetching the func host's Event Grid system key from Azurite...")
    function_key = _fetch_eventgrid_key(client)
    if not function_key:
        print(
            "  ... gave up waiting for the Event Grid system key; relaying "
            "without one (events will likely be rejected with 401)"
        )

    seen: set[str] = set()
    print(f"Watching Azurite container '{container}' for new KML/KMZ uploads...")
    print(f"Relaying to {func_base} as Event Grid function '{function_name}'.")

    while True:
        try:
            current = {blob.name for blob in container_client.list_blobs()}
        except Exception as exc:  # Azurite not up yet / transient — keep polling
            print(f"  ... list_blobs failed ({exc}), retrying")
            time.sleep(poll_interval)
            continue

        for blob_name in _new_blobs(seen, current):
            seen.add(blob_name)
            if not _is_relayable_blob(blob_name):
                continue
            _relay_one(
                container_client, container, blob_name, function_name, func_base, function_key
            )

        time.sleep(poll_interval)


def _relay_one(
    container_client,
    container: str,
    blob_name: str,
    function_name: str,
    func_base: str,
    function_key: str | None,
) -> None:
    """Fire one blob's synthetic Event Grid event. Errors are logged, not raised."""
    try:
        props = container_client.get_blob_client(blob_name).get_blob_properties()
    except Exception as exc:
        print(f"  ... could not read properties for {blob_name} ({exc}), skipping")
        return

    print(f"New upload detected: {blob_name}")
    blob_url = f"{AZURITE_BLOB_BASE}/{container}/{blob_name}"
    try:
        fire_event_grid(
            blob_url=blob_url,
            blob_name=blob_name,
            content_length=props.size,
            container=container,
            function_name=function_name,
            function_key=function_key,
            func_base=func_base,
            strict=False,
        )
    except Exception as exc:
        print(f"  ... failed to relay {blob_name} ({exc})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default=DEFAULT_CONTAINER, help="Blob container to watch")
    parser.add_argument("--func-base", default=DEFAULT_FUNC_BASE, help="Functions host base URL")
    parser.add_argument(
        "--function-name",
        default=DEFAULT_EVENT_GRID_FUNCTION_NAME,
        help="Event Grid function name (default: blob_trigger)",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=POLL_INTERVAL_SECONDS, help="Seconds between polls"
    )
    args = parser.parse_args()

    try:
        relay_forever(
            container=args.container,
            func_base=args.func_base,
            function_name=args.function_name,
            poll_interval=args.poll_interval,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

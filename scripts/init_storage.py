"""Bootstrap Azurite blob containers required by the pipeline.

Usage: uv run python scripts/init_storage.py
"""

from __future__ import annotations

import os
import sys
import time

from _azurite import AZURITE_BLOB_HOST, AZURITE_CONN_STR, CONTAINERS, azurite_blob_reachable
from azure.storage.blob import BlobServiceClient


def _clear_proxy_env() -> None:
    """Avoid proxy env vars hijacking local Azurite traffic."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY"):
        os.environ.pop(var, None)
        os.environ.pop(var.lower(), None)


def wait_for_azurite(client: BlobServiceClient, retries: int = 15, delay: float = 2.0) -> None:
    """Block until Azurite responds, or exit after *retries* attempts."""
    for attempt in range(1, retries + 1):
        if not azurite_blob_reachable(timeout=delay):
            if attempt == retries:
                print("ERROR: Azurite is not reachable on the blob endpoint. Is it running?")
                print("  Start it with: make dev-up")
                sys.exit(1)
            print(f"  Waiting for Azurite socket (attempt {attempt}/{retries})...")
            time.sleep(delay)
            continue
        try:
            client.get_account_information()
            return
        except Exception:
            if attempt == retries:
                print("ERROR: Azurite is not responding. Is it running?")
                print("  Start it with: make dev-up")
                sys.exit(1)
            print(f"  Waiting for Azurite (attempt {attempt}/{retries})...")
            time.sleep(delay)


def main() -> None:
    """Connect to Azurite and ensure all required containers exist."""
    print(f"Connecting to Azurite (AZURITE_BLOB_HOST={AZURITE_BLOB_HOST})...")
    _clear_proxy_env()
    client = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    wait_for_azurite(client)
    print("Azurite is ready.")

    for name in CONTAINERS:
        container = client.get_container_client(name)
        if container.exists():
            print(f"  Container '{name}' already exists.")
        else:
            container.create_container()
            print(f"  Created container '{name}'.")

    print("Storage initialisation complete.")


if __name__ == "__main__":
    main()

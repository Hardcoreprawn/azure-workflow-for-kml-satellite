"""Bootstrap Azurite blob containers required by the pipeline.

Usage: uv run python scripts/init_storage.py
"""

from __future__ import annotations

import sys
import time

from _azurite import AZURITE_CONN_STR, CONTAINERS
from azure.storage.blob import BlobServiceClient


def wait_for_azurite(client: BlobServiceClient, retries: int = 15, delay: float = 2.0) -> None:
    """Block until Azurite responds, or exit after *retries* attempts."""
    for attempt in range(1, retries + 1):
        try:
            client.get_account_information()
            return
        except Exception:
            if attempt == retries:
                print("ERROR: Azurite is not responding. Is it running?")
                print("  Start it with: docker compose up -d")
                sys.exit(1)
            print(f"  Waiting for Azurite (attempt {attempt}/{retries})...")
            time.sleep(delay)


def main() -> None:
    """Connect to Azurite and ensure all required containers exist."""
    print("Connecting to Azurite...")
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

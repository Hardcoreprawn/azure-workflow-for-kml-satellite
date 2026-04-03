"""Create Azurite blob containers for docker-compose.

Installs azure-storage-blob at runtime (kept out of the slim image layer)
and uses the well-known Azurite connection string.

NOTE: This file intentionally duplicates constants from ``scripts/_azurite.py``.
In docker-compose the script is volume-mounted as a single file
(``/app/init_storage_docker.py``) into a bare ``uv:python3.12`` image —
``_azurite.py`` is NOT available on ``sys.path`` inside that container.
The duplication also lets us use ``os.environ.get`` overrides (the Docker
service sets ``AZURITE_BLOB_HOST=azurite``) which ``_azurite.py`` does not
support.
"""

from __future__ import annotations

import os
import sys
import time

HOST = os.environ.get("AZURITE_BLOB_HOST", "127.0.0.1")
PORT = int(os.environ.get("AZURITE_BLOB_PORT", "10000"))
CONTAINERS = ["kml-input", "kml-output", "pipeline-payloads"]

CONN_STR = (
    f"DefaultEndpointsProtocol=http;"
    f"AccountName=devstoreaccount1;"
    f"AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq"  # pragma: allowlist secret
    f"/K1SZFPTOtr/KBHBeksoGMGw==;"
    f"BlobEndpoint=http://{HOST}:{PORT}/devstoreaccount1;"
)


def _ensure_sdk() -> None:
    """Install azure-storage-blob if not already present."""
    try:
        import azure.storage.blob  # noqa: F401
    except ImportError:
        import subprocess

        subprocess.check_call(
            ["uv", "pip", "install", "--system", "-q", "azure-storage-blob"],
        )


def wait_for_azurite(retries: int = 15, delay: float = 2.0) -> None:
    import urllib.error
    import urllib.request

    for attempt in range(1, retries + 1):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/", timeout=3)
            return
        except urllib.error.HTTPError:
            return  # Any HTTP response means Azurite is up
        except (urllib.error.URLError, OSError):
            if attempt == retries:
                print("ERROR: Azurite is not responding.")
                sys.exit(1)
            print(f"  Waiting for Azurite ({attempt}/{retries})...")
            time.sleep(delay)


def main() -> None:
    print("Waiting for Azurite...")
    wait_for_azurite()
    print("Azurite is ready.")

    _ensure_sdk()
    from azure.storage.blob import BlobServiceClient

    client = BlobServiceClient.from_connection_string(CONN_STR)
    print("Creating containers...")
    for name in CONTAINERS:
        container = client.get_container_client(name)
        if container.exists():
            print(f"  '{name}' already exists.")
        else:
            container.create_container()
            print(f"  Created '{name}'.")
    print("Storage init complete.")


if __name__ == "__main__":
    main()

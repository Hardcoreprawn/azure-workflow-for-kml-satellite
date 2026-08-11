"""Shared Azurite configuration for local dev scripts.

Single source of truth for the well-known Azurite development credentials.
Imported by ``init_storage.py``, ``simulate_upload.py``, and integration tests.
"""

from __future__ import annotations

import os
import socket
from typing import Final

__all__ = [
    "AZURITE_ACCOUNT_KEY",
    "AZURITE_ACCOUNT_NAME",
    "AZURITE_BLOB_BASE",
    "AZURITE_BLOB_HOST",
    "AZURITE_BLOB_PORT",
    "AZURITE_CONN_STR",
    "AZURITE_QUEUE_PORT",
    "AZURITE_TABLE_PORT",
    "CONTAINERS",
    "azurite_blob_reachable",
]

AZURITE_ACCOUNT_NAME: Final[str] = "devstoreaccount1"
AZURITE_ACCOUNT_KEY: Final[str] = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="  # pragma: allowlist secret
)
# Host defaults to loopback for local dev. CI runs the gate jobs *inside* the
# dev container with Azurite as a `services:` container reachable by its network
# alias, so the host is overridable via the AZURITE_BLOB_HOST env var (the same
# knob init_storage_docker.py already honours). See #1086.
AZURITE_BLOB_HOST: Final[str] = os.environ.get("AZURITE_BLOB_HOST", "127.0.0.1")
AZURITE_BLOB_PORT: Final[int] = 10000
AZURITE_QUEUE_PORT: Final[int] = 10001
AZURITE_TABLE_PORT: Final[int] = 10002

AZURITE_BLOB_BASE: Final[str] = f"http://{AZURITE_BLOB_HOST}:{AZURITE_BLOB_PORT}/{AZURITE_ACCOUNT_NAME}"

AZURITE_CONN_STR: Final[str] = (
    f"DefaultEndpointsProtocol=http;"
    f"AccountName={AZURITE_ACCOUNT_NAME};"
    f"AccountKey={AZURITE_ACCOUNT_KEY};"
    f"BlobEndpoint=http://{AZURITE_BLOB_HOST}:{AZURITE_BLOB_PORT}/{AZURITE_ACCOUNT_NAME};"
    f"QueueEndpoint=http://{AZURITE_BLOB_HOST}:{AZURITE_QUEUE_PORT}/{AZURITE_ACCOUNT_NAME};"
    f"TableEndpoint=http://{AZURITE_BLOB_HOST}:{AZURITE_TABLE_PORT}/{AZURITE_ACCOUNT_NAME};"
)

CONTAINERS: Final[list[str]] = [
    "kml-input",
    "kml-output",
    "pipeline-payloads",
]


def azurite_blob_reachable(
    *, host: str = AZURITE_BLOB_HOST, port: int = AZURITE_BLOB_PORT, timeout: float = 0.5
) -> bool:
    """Fast, retry-free check for whether Azurite's blob endpoint is listening.

    Deliberately a raw TCP connect, not an Azure SDK client call: SDK clients
    apply their default retry policy (multiple attempts with exponential
    backoff) on a connection failure, which turns a simple "is anything
    listening" probe into tens of seconds of retried sleeps. Callers that use
    this to gate a ``pytest.mark.skipif`` evaluate it at collection time —
    for every invocation, even when the tests it guards are deselected — so
    it must stay bounded and fast regardless of whether Azurite is running.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

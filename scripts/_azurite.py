"""Shared Azurite configuration for local dev scripts.

Single source of truth for the well-known Azurite development credentials.
Imported by ``init_storage.py``, ``simulate_upload.py``, and integration tests.
"""

from __future__ import annotations

import os
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

AZURITE_BLOB_BASE: Final[str] = (
    f"http://{AZURITE_BLOB_HOST}:{AZURITE_BLOB_PORT}/{AZURITE_ACCOUNT_NAME}"
)

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

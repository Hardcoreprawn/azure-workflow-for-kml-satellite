"""Blob URL validation helpers for Event Grid blob-created events.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import re
from typing import Any
from urllib.parse import urlparse

from treesight.constants import MAX_KML_FILE_SIZE_BYTES
from treesight.errors import ContractError


def _expected_blob_host() -> str:
    """Derive the expected Azure Blob hostname from the connection string
    or the storage account name (managed identity).

    Returns the hostname of the configured storage account so callers
    can validate that an incoming blob URL belongs to *our* account,
    not just any ``*.blob.core.windows.net`` host.
    """
    from treesight.config import STORAGE_ACCOUNT_NAME, STORAGE_CONNECTION_STRING

    conn = STORAGE_CONNECTION_STRING or ""

    # Azurite / emulator shorthand
    if conn.strip().lower() == "usedevelopmentstorage=true":
        return "devstoreaccount1.blob.core.windows.net"

    # Prefer explicit BlobEndpoint (handles Azurite and custom endpoints)
    m = re.search(r"BlobEndpoint=([^;]+)", conn, re.IGNORECASE)
    if m:
        parsed = urlparse(m.group(1))
        return (parsed.hostname or "").lower()

    # Fall back to AccountName → <account>.blob.core.windows.net
    m = re.search(r"AccountName=([^;]+)", conn, re.IGNORECASE)
    if m:
        return f"{m.group(1).lower()}.blob.core.windows.net"

    # Managed identity: derive from account name
    if STORAGE_ACCOUNT_NAME:
        return f"{STORAGE_ACCOUNT_NAME.lower()}.blob.core.windows.net"

    return ""


def _is_trusted_blob_host(host: str) -> bool:
    """Return True if *host* is the configured storage account or Azurite."""
    expected = _expected_blob_host()
    if expected and host == expected:
        return True
    # Azurite IP-based URLs (127.0.0.1, localhost, azurite)
    return host in ("127.0.0.1", "localhost", "azurite")


def _extract_container(blob_url: str) -> str:
    parsed = urlparse(blob_url)
    host = (parsed.hostname or "").lower()
    if not _is_trusted_blob_host(host):
        return ""
    if host.endswith(".blob.core.windows.net"):
        # https://<account>.blob.core.windows.net/<container>/<blob>
        parts = parsed.path.lstrip("/").split("/")
        return parts[0] if parts else ""
    # Azurite with IP: http://127.0.0.1:10000/devstoreaccount1/container/blob
    parts = parsed.path.lstrip("/").split("/")
    if len(parts) >= 2 and parts[0] == "devstoreaccount1":
        return parts[1]
    return ""


def _extract_blob_name(blob_url: str) -> str:
    parsed = urlparse(blob_url)
    host = (parsed.hostname or "").lower()
    if not _is_trusted_blob_host(host):
        return ""
    if host.endswith(".blob.core.windows.net"):
        parts = parsed.path.lstrip("/").split("/")
        return "/".join(parts[1:]) if len(parts) > 1 else ""
    # Azurite with IP: http://127.0.0.1:10000/devstoreaccount1/container/blob
    parts = parsed.path.lstrip("/").split("/")
    if len(parts) >= 3 and parts[0] == "devstoreaccount1":
        return "/".join(parts[2:])
    return ""


def _validate_blob_event(blob_name: str, container_name: str, data: dict[str, Any]) -> None:
    if not blob_name:
        raise ContractError("Blob name is empty", code="EMPTY_BLOB_NAME")
    if not (blob_name.lower().endswith(".kml") or blob_name.lower().endswith(".kmz")):
        raise ContractError("Not a .kml or .kmz file", code="INVALID_FILE_TYPE")
    if not container_name:
        raise ContractError("Container name is empty", code="EMPTY_CONTAINER_NAME")
    if not container_name.endswith("-input"):
        raise ContractError("Container must end with -input", code="INVALID_CONTAINER")
    content_length = data.get("contentLength", 0)
    if content_length < 0:
        raise ContractError("Negative content length", code="INVALID_CONTENT_LENGTH")
    if content_length == 0:
        raise ContractError("Empty blob", code="EMPTY_BLOB")
    if content_length > MAX_KML_FILE_SIZE_BYTES:
        raise ContractError(f"File exceeds {MAX_KML_FILE_SIZE_BYTES} bytes", code="FILE_TOO_LARGE")

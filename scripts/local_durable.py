"""Local-only Durable management polling for storage-native fixtures."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx
from _azurite import AZURITE_CONN_STR
from azure.storage.blob import BlobServiceClient


def validate_local_host(base: str) -> None:
    if urlsplit(base).hostname not in {"localhost", "127.0.0.1", "func", "orch"}:
        raise ValueError("Local fixture management polling requires a local Functions host")


def local_durable_keys(base: str) -> list[str]:
    validate_local_host(base)
    service = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    container = service.get_container_client("azure-webjobs-secrets")
    keys = []
    for blob in container.list_blobs():
        payload = json.loads(container.get_blob_client(blob.name).download_blob().readall())
        for key in payload.get("systemKeys", []):
            if key.get("name") == "durabletask_extension" and isinstance(key.get("value"), str):
                keys.append(key["value"])
    if not keys:
        raise RuntimeError("Local Durable extension key unavailable")
    return keys


def fetch_poll_status(
    url: str, *, timeout: float = 10.0, management_keys: list[str] | None = None
) -> tuple[int | None, str, dict[str, Any] | None]:
    validate_local_host(url)
    try:
        response = None if management_keys else httpx.get(url, timeout=timeout)
        if response is None or response.status_code in {401, 403}:
            for key in management_keys or local_durable_keys(url):
                response = httpx.get(url, timeout=timeout, headers={"x-functions-key": key})
                if response.status_code not in {401, 403}:
                    break
    except httpx.TransportError:
        return None, "transport_error", None
    if response is None:
        raise RuntimeError("Local Durable extension key unavailable")
    if response.status_code == 429:
        return 429, "rate_limited", None
    if response.status_code == 404:
        return 404, "not_found", None
    if response.status_code != 200:
        return response.status_code, "http_error", None
    try:
        payload = response.json()
    except ValueError:
        return 200, "invalid_json", None
    statuses = {"Completed", "Failed", "Canceled", "Terminated", "Pending", "Running", "ContinuedAsNew", "Suspended"}
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("runtimeStatus"), str)
        or payload["runtimeStatus"] not in statuses
    ):
        return 200, "invalid_status", None
    from blueprints.pipeline._status import _reshape_output

    if isinstance(payload.get("output"), dict):
        payload = {**payload, "output": _reshape_output(payload["output"])}
    return 200, "status", payload

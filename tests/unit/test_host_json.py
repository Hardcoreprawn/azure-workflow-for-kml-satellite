"""Validation tests for host.json runtime configuration.

These tests enforce documented Durable Functions host settings that are required
for reliable startup in containerized Azure Functions deployments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
HOST_JSON = ROOT / "host.json"


def _load_host_json() -> dict[str, Any]:
    assert HOST_JSON.exists(), f"host.json not found at {HOST_JSON}"
    return json.loads(HOST_JSON.read_text(encoding="utf-8"))


def test_host_json_is_v2_schema() -> None:
    """Host config must use Functions host v2+ schema format."""
    host = _load_host_json()
    assert host.get("version") == "2.0"


def test_durable_storage_provider_is_runtime_supported() -> None:
    """Durable storage provider type must match runtime-supported provider name."""
    host = _load_host_json()
    durable = host.get("extensions", {}).get("durableTask", {}).get("storageProvider", {})
    provider_type = durable.get("type")
    assert provider_type == "AzureStorage", (
        "Durable storage provider must be 'AzureStorage' for the Azure Storage backend"
    )


def test_extension_bundle_is_v4_series() -> None:
    """Extension bundle range must remain on v4 series for this app."""
    host = _load_host_json()
    bundle = host.get("extensionBundle", {})
    assert bundle.get("id") == "Microsoft.Azure.Functions.ExtensionBundle"
    assert str(bundle.get("version", "")).startswith("[4.*")

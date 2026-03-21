"""Payload offloading for large payloads (§7.5)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from treesight.constants import PAYLOAD_OFFLOAD_THRESHOLD_BYTES, PIPELINE_PAYLOADS_CONTAINER
from treesight.storage.client import BlobStorageClient


class PayloadOffloader:
    """Offloads payloads exceeding the Durable Functions history limit."""

    def __init__(self, storage: BlobStorageClient | None = None) -> None:
        self._storage = storage or BlobStorageClient()

    def should_offload(self, data: list[dict[str, Any]]) -> bool:
        """Return ``True`` if *data* exceeds the offload threshold."""
        serialised = json.dumps(data, default=str).encode("utf-8")
        return len(serialised) > PAYLOAD_OFFLOAD_THRESHOLD_BYTES

    def offload(self, instance_id: str, data: list[dict[str, Any]]) -> dict[str, Any]:
        """Upload *data* to blob storage and return a ref pointer."""
        serialised = json.dumps(data, default=str).encode("utf-8")
        content_hash = hashlib.sha256(serialised).hexdigest()[:16]
        blob_path = f"payloads/{instance_id}/{content_hash}.json"
        self._storage.upload_bytes(
            PIPELINE_PAYLOADS_CONTAINER,
            blob_path,
            serialised,
            content_type="application/json",
        )
        return {"ref": blob_path, "count": len(data)}

    def load_all(self, ref: str) -> list[dict[str, Any]]:
        """Download the full payload list from *ref*."""
        return self._storage.download_json_list(PIPELINE_PAYLOADS_CONTAINER, ref)

    def load_single(self, ref: str, index: int) -> dict[str, Any]:
        """Download the payload list and return the item at *index*."""
        items = self.load_all(ref)
        return items[index]

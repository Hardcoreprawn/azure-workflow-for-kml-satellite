"""Payload offloading and claim check for large payloads (§7.5).

Supports two patterns:

1. **Bulk offload** — Store a full list and return a single ``ref`` pointer.
   Used when orchestrator history entries would exceed 48 KiB.

2. **Claim check** — Store individual items keyed by ID and return lightweight
   refs.  Used for per-AOI geometry so the orchestrator never passes large
   dicts between phases.
"""

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

    # ------------------------------------------------------------------
    # Bulk offload
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Claim check (per-item storage)
    # ------------------------------------------------------------------

    def store_claim(
        self,
        instance_id: str,
        claim_id: str,
        data: dict[str, Any],
    ) -> str:
        """Store a single item under a unique claim path and return the ref."""
        blob_path = f"claims/{instance_id}/{claim_id}.json"
        serialised = json.dumps(data, default=str).encode("utf-8")
        self._storage.upload_bytes(
            PIPELINE_PAYLOADS_CONTAINER,
            blob_path,
            serialised,
            content_type="application/json",
        )
        return blob_path

    def load_claim(self, ref: str) -> dict[str, Any]:
        """Download a single claim-checked item."""
        raw = self._storage.download_bytes(PIPELINE_PAYLOADS_CONTAINER, ref)
        return json.loads(raw)

    def store_claims_batch(
        self,
        instance_id: str,
        items: list[dict[str, Any]],
        key_field: str = "feature_name",
    ) -> list[dict[str, str]]:
        """Store every item and return lightweight ``{claim_id, ref, key}`` refs.

        Each item is stored individually so activities can retrieve only the
        data they need.
        """
        refs: list[dict[str, str]] = []
        for idx, item in enumerate(items):
            raw_key = item.get(key_field)
            key = str(raw_key) if raw_key is not None else f"item_{idx}"
            claim_id = f"{key_field}_{idx}_{_short_hash(key)}"
            blob_ref = self.store_claim(instance_id, claim_id, item)
            refs.append({"claim_id": claim_id, "ref": blob_ref, "key": key})
        return refs


def _short_hash(value: str) -> str:
    """Return a short deterministic hash for *value*."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]

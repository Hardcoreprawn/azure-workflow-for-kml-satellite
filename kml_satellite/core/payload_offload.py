"""Large-payload offloading for Durable Functions orchestration history (Issue #62).

Azure Durable Functions stores every activity input and output in
orchestration history (Azure Storage tables / queues).  Message size
limits (64 KB - 1 MB depending on tier) mean that activities returning
large lists — such as ``parse_kml`` with thousands of features — can
cause ``OrchestrationFailure`` crashes.

This module provides helpers to:

- **offload** a large list to a blob and return a tiny reference dict,
- **detect** whether an activity result is an offloaded reference,
- **build** per-item activity inputs from a reference, and
- **resolve** those inputs back to the original item inside downstream
  activities.

Design choices:
    • One JSON blob for the whole list (cheap single write/read).
    • Downstream activities each read the blob and index into it;
      blob reads are fast and Azure Functions workers cache connections.
    • Small payloads pass through unchanged — zero overhead for the
      common case.

References:
    PID 7.4.2  (Fail Loudly, Fail Safely)
    Issue #62
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from azure.storage.blob import BlobServiceClient

logger = logging.getLogger("kml_satellite.core.payload_offload")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OFFLOAD_THRESHOLD_BYTES: int = 48 * 1024
"""Payloads larger than this (in bytes of compact JSON) are offloaded."""

PAYLOAD_CONTAINER: str = "pipeline-payloads"
"""Default blob container for offloaded payloads."""

OFFLOAD_SENTINEL: str = "__payload_offloaded__"
"""Marker key in offloaded reference dicts."""

REF_KEY: str = "__payload_ref__"
"""Marker key in activity inputs containing a payload reference."""

INDEX_KEY: str = "__payload_index__"
"""Key in activity inputs specifying which item to read."""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def is_offloaded(data: object) -> bool:
    """Return ``True`` if *data* is an offloaded payload reference dict."""
    return isinstance(data, dict) and data.get(OFFLOAD_SENTINEL) is True


# ---------------------------------------------------------------------------
# Offload
# ---------------------------------------------------------------------------


def offload_if_large(
    payload: list[dict[str, Any]],
    *,
    blob_path: str,
    blob_service_client: BlobServiceClient,
    container: str = PAYLOAD_CONTAINER,
    threshold_bytes: int = OFFLOAD_THRESHOLD_BYTES,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Return *payload* as-is if small, or offload to blob and return a reference.

    Args:
        payload: The list of dicts to potentially offload.
        blob_path: Blob path within *container* (e.g.
            ``"payloads/<correlation_id>/features.json"``).
        blob_service_client: An ``azure.storage.blob.BlobServiceClient``.
        container: Blob container name.
        threshold_bytes: Size threshold above which offloading triggers.

    Returns:
        The original *payload* list if it fits within *threshold_bytes*,
        otherwise a small reference dict with ``__payload_offloaded__``
        set to ``True``.
    """
    serialized = json.dumps(payload, separators=(",", ":"))
    size_bytes = len(serialized.encode("utf-8"))

    if size_bytes <= threshold_bytes:
        return payload

    import contextlib

    container_client = blob_service_client.get_container_client(container)
    with contextlib.suppress(Exception):
        container_client.create_container()

    blob_client = blob_service_client.get_blob_client(container=container, blob=blob_path)
    blob_client.upload_blob(serialized.encode("utf-8"), overwrite=True)

    # Also write per-item blobs so resolve_ref_input reads only one item (O(1))
    stem = blob_path.rsplit(".", 1)[0] if "." in blob_path else blob_path
    for i, item in enumerate(payload):
        item_path = f"{stem}/{i}.json"
        item_bytes = json.dumps(item, separators=(",", ":")).encode("utf-8")
        blob_service_client.get_blob_client(container=container, blob=item_path).upload_blob(
            item_bytes, overwrite=True
        )

    logger.info(
        "Offloaded payload to blob | container=%s | path=%s | items=%d | size=%d bytes",
        container,
        blob_path,
        len(payload),
        size_bytes,
    )

    return {
        OFFLOAD_SENTINEL: True,
        "container": container,
        "blob_path": blob_path,
        "item_blob_stem": stem,
        "count": len(payload),
        "size_bytes": size_bytes,
    }


# ---------------------------------------------------------------------------
# Build per-item activity inputs from a reference
# ---------------------------------------------------------------------------


def build_ref_input(offloaded_ref: dict[str, Any], index: int) -> dict[str, Any]:
    """Build an activity input dict that references one item in an offloaded payload.

    The returned dict contains ``__payload_ref__`` and ``__payload_index__``
    keys.  Downstream activities use ``resolve_ref_input`` to hydrate.

    Args:
        offloaded_ref: The reference dict returned by ``offload_if_large``.
        index: Zero-based index of the item to reference.

    Returns:
        A small dict suitable for passing as an activity input.
    """
    return {
        REF_KEY: {
            "container": offloaded_ref["container"],
            "blob_path": offloaded_ref["blob_path"],
            "item_blob_stem": offloaded_ref.get("item_blob_stem", ""),
            "count": offloaded_ref["count"],
        },
        INDEX_KEY: index,
    }


# ---------------------------------------------------------------------------
# Resolve payload references in activity inputs
# ---------------------------------------------------------------------------


def resolve_ref_input(
    payload: dict[str, Any],
    *,
    blob_service_client: BlobServiceClient,
) -> dict[str, Any]:
    """If *payload* is a blob reference, read the item from blob; otherwise pass through.

    Args:
        payload: The raw activity input dict.
        blob_service_client: An ``azure.storage.blob.BlobServiceClient``.

    Returns:
        The resolved item dict (either the original or fetched from blob).

    Raises:
        IndexError: If the referenced index is out of range.
        ContractError: If the blob cannot be read or parsed.
    """
    from kml_satellite.core.exceptions import ContractError

    ref = payload.get(REF_KEY)
    if ref is None or not isinstance(ref, dict):
        return payload

    index = int(payload.get(INDEX_KEY, 0))
    container = str(ref["container"])
    blob_path = str(ref["blob_path"])
    item_blob_stem = str(ref.get("item_blob_stem", ""))

    # Prefer per-item blob (O(1) download) when available
    if item_blob_stem:
        item_blob_path = f"{item_blob_stem}/{index}.json"
        try:
            blob_client = blob_service_client.get_blob_client(
                container=container, blob=item_blob_path
            )
            data = blob_client.download_blob().readall()
        except Exception as exc:
            msg = f"Failed to download per-item payload blob {container}/{item_blob_path}: {exc}"
            raise ContractError(msg) from exc

        try:
            item: dict[str, Any] = json.loads(data)
        except (json.JSONDecodeError, TypeError) as exc:
            msg = (
                f"Failed to decode per-item payload JSON from {container}/{item_blob_path}: {exc}"
            )
            raise ContractError(msg) from exc

        if not isinstance(item, dict):
            msg = (
                f"Per-item payload at {container}/{item_blob_path} "
                f"is not a dict: {type(item).__name__}"
            )
            raise ContractError(msg)

        logger.debug(
            "Resolved per-item payload ref | container=%s | path=%s",
            container,
            item_blob_path,
        )
        return item

    # Fallback: read the full list blob and index into it
    try:
        blob_client = blob_service_client.get_blob_client(container=container, blob=blob_path)
        data = blob_client.download_blob().readall()
    except Exception as exc:
        msg = f"Failed to download offloaded payload blob {container}/{blob_path}: {exc}"
        raise ContractError(msg) from exc

    try:
        items: list[dict[str, Any]] = json.loads(data)
    except (json.JSONDecodeError, TypeError) as exc:
        msg = f"Failed to decode offloaded payload JSON from {container}/{blob_path}: {exc}"
        raise ContractError(msg) from exc

    if not isinstance(items, list):
        msg = f"Offloaded payload at {container}/{blob_path} is not a list: {type(items).__name__}"
        raise ContractError(msg)

    if index < 0 or index >= len(items):
        msg = f"Payload ref index {index} out of range (0..{len(items) - 1})"
        raise IndexError(msg)

    logger.debug(
        "Resolved payload ref | container=%s | path=%s | index=%d/%d",
        container,
        blob_path,
        index,
        len(items),
    )

    return items[index]

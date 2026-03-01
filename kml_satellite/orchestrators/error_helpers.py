"""Error dict builders for orchestrator failures.

Consolidates contract-shaped error dict builders used across the fulfillment
phase to ensure consistent error responses for download and post-process failures.

Issue #104: Extracted from phases.py to enable reuse and testing.
"""

from __future__ import annotations

from typing import Any


def download_error_dict(
    outcome: dict[str, Any],
    error: str,
    *,
    state: str = "failed",
) -> dict[str, Any]:
    """Build a contract-shaped error dict for a failed download.

    Used when ``download_imagery`` activity fails or is not attempted.
    Preserves order/scene metadata from the acquisition outcome and
    fills in failed state defaults for download-specific fields.

    Args:
        outcome: Dict from ``acquire_imagery`` activity with order_id,
            scene_id, provider, aoi_feature_name, etc.
        error: Human-readable error message.
        state: Outcome state (default "failed")).

    Returns:
        Dict matching the download result contract (18 fields).
    """
    return {
        "state": state,
        "order_id": str(outcome.get("order_id", "")),
        "scene_id": str(outcome.get("scene_id", "")),
        "provider": str(outcome.get("provider", "")),
        "aoi_feature_name": str(outcome.get("aoi_feature_name", "")),
        "blob_path": "",
        "adapter_blob_path": "",
        "container": "",
        "size_bytes": 0,
        "content_type": "",
        "download_duration_seconds": 0.0,
        "retry_count": 0,
        "error": error,
    }


def post_process_error_dict(
    dl_result: dict[str, Any],
    error: str,
    *,
    state: str = "failed",
) -> dict[str, Any]:
    """Build a contract-shaped error dict for a failed post-process.

    Used when ``clip_imagery`` or ``reproject_imagery`` activities fail.
    Preserves download metadata (order_id, blob_path, container) and
    captures the specific post-process error.

    Args:
        dl_result: Dict from ``download_imagery`` activity with order_id,
            blob_path, container, etc.
        error: Human-readable error message describing the post-process failure.
        state: Outcome state (default "failed").

    Returns:
        Dict matching the post-process result contract (17 fields).
    """
    return {
        "state": state,
        "order_id": dl_result.get("order_id", ""),
        "source_blob_path": dl_result.get("blob_path", ""),
        "clipped_blob_path": "",
        "container": dl_result.get("container", ""),
        "clipped": False,
        "reprojected": False,
        "source_crs": "",
        "target_crs": "",
        "source_size_bytes": 0,
        "output_size_bytes": 0,
        "processing_duration_seconds": 0.0,
        "clip_error": error,
        "error": error,
    }

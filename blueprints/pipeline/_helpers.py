"""Pipeline helpers: constants, validation, response shaping.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
from typing import Any

import azure.functions as func

from treesight.constants import MAX_KML_FILE_SIZE_BYTES
from treesight.errors import ContractError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_ANALYSIS_BODY_BYTES = 131_072


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _cosmos_available() -> bool:
    """Return True if Cosmos DB is configured for run storage."""
    from treesight import config

    return bool(config.COSMOS_ENDPOINT)


def _error_response(status: int, message: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# Blob event helpers
# ---------------------------------------------------------------------------


def _validate_blob_event(blob_name: str, container_name: str, data: dict[str, Any]) -> None:
    if not blob_name:
        raise ContractError("Blob name is empty", code="EMPTY_BLOB_NAME")
    if not blob_name.lower().endswith(".kml"):
        raise ContractError("Not a .kml file", code="INVALID_FILE_TYPE")
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


def _extract_container(blob_url: str) -> str:
    parts = blob_url.split("/")
    for i, p in enumerate(parts):
        if (p.endswith(".blob.core.windows.net") or p == "devstoreaccount1") and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _extract_blob_name(blob_url: str) -> str:
    parts = blob_url.split("/")
    for i, p in enumerate(parts):
        if (p.endswith(".blob.core.windows.net") or p == "devstoreaccount1") and i + 2 < len(parts):
            return "/".join(parts[i + 2 :])
    return ""


# ---------------------------------------------------------------------------
# Durable status / output shaping
# ---------------------------------------------------------------------------


def _durable_status_payload(status: Any) -> dict[str, Any]:
    return {
        "instanceId": status.instance_id,
        "name": status.name,
        "runtimeStatus": status.runtime_status.value if status.runtime_status else None,
        "createdTime": str(status.created_time),
        "lastUpdatedTime": str(status.last_updated_time),
        "customStatus": status.custom_status,
        "output": _reshape_output(status.output) if status.output else None,
    }


def _reshape_output(output: dict[str, Any]) -> dict[str, Any]:
    """Reshape PipelineSummary to the diagnostics contract (§4.3)."""
    result = {
        "status": output.get("status", ""),
        "message": output.get("message", ""),
        "blobName": output.get("blob_name", ""),
        "featureCount": output.get("feature_count", 0),
        "aoiCount": output.get("aoi_count", 0),
        "metadataCount": output.get("metadata_count", 0),
        "imageryReady": output.get("imagery_ready", 0),
        "imageryFailed": output.get("imagery_failed", 0),
        "downloadsCompleted": output.get("downloads_completed", 0),
        "downloadsFailed": output.get("downloads_failed", 0),
        "postProcessCompleted": output.get("post_process_completed", 0),
        "postProcessFailed": output.get("post_process_failed", 0),
        "artifacts": output.get("artifacts", {}),
    }
    if output.get("enrichment_manifest"):
        result["enrichmentManifest"] = output["enrichment_manifest"]
    if output.get("enrichment_duration"):
        result["enrichmentDuration"] = output["enrichment_duration"]
    return result


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------


def _collect_enrichment_coords(aois: list[dict[str, Any]]) -> list[list[float]]:
    """Extract representative coordinates from AOIs for enrichment."""
    all_coords: list[list[float]] = []
    for aoi in aois:
        ext = aoi.get("exterior_coords", [])
        if ext:
            all_coords.extend(ext)

    if not all_coords:
        for aoi in aois:
            bb = aoi.get("bbox") or aoi.get("buffered_bbox")
            if bb and len(bb) == 4:
                min_lon, min_lat, max_lon, max_lat = bb
                all_coords = [
                    [min_lon, min_lat],
                    [max_lon, min_lat],
                    [max_lon, max_lat],
                    [min_lon, max_lat],
                    [min_lon, min_lat],
                ]
                break
    return all_coords


def _build_order_lookups(
    orders: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Build asset URL and order metadata lookup dicts from order results."""
    asset_urls: dict[str, str] = {o.get("order_id", ""): o.get("asset_url", "") for o in orders}
    order_meta: dict[str, dict[str, str]] = {
        o.get("order_id", ""): {
            "role": o.get("role", ""),
            "collection": o.get("collection", ""),
        }
        for o in orders
    }
    return asset_urls, order_meta


def _acq_payload(
    ref: dict[str, str],
    inp: dict[str, Any],
    composite: bool,
) -> dict[str, Any]:
    """Build a single acquisition activity payload from a claim ref."""
    base: dict[str, Any] = {
        "aoi_ref": ref["ref"],
        "provider_name": inp.get("provider_name", "planetary_computer"),
        "provider_config": inp.get("provider_config"),
        "imagery_filters": inp.get("imagery_filters"),
    }
    if composite:
        from treesight.config import config_get_int

        base["temporal_count"] = config_get_int(inp, "temporal_count", 6)
    return base


def _poll_payload(order: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    """Build a single poll_order activity payload."""
    return {
        "order_id": order.get("order_id", ""),
        "scene_id": order.get("scene_id", ""),
        "aoi_feature_name": order.get("aoi_feature_name", ""),
        "provider_name": inp.get("provider_name", "planetary_computer"),
        "provider_config": inp.get("provider_config"),
        "overrides": inp,
    }


def _download_payload(
    outcome: dict[str, Any],
    inp: dict[str, Any],
    ctx: dict[str, str],
    asset_urls: dict[str, str],
    order_meta: dict[str, dict[str, str]],
    aoi_ref_lookup: dict[str, str],
    output_container: str,
) -> dict[str, Any]:
    """Build a single download_imagery activity payload."""
    oid = outcome.get("order_id", "")
    return {
        "outcome": outcome,
        "asset_url": asset_urls.get(oid, ""),
        "aoi_ref": aoi_ref_lookup.get(outcome.get("aoi_feature_name", "")),
        "role": order_meta.get(oid, {}).get("role", ""),
        "collection": order_meta.get(oid, {}).get("collection", ""),
        "provider_name": inp.get("provider_name", "planetary_computer"),
        "provider_config": inp.get("provider_config"),
        "project_name": ctx["project_name"],
        "timestamp": ctx["timestamp"],
        "output_container": output_container,
    }


def _post_process_payload(
    dl: dict[str, Any],
    inp: dict[str, Any],
    ctx: dict[str, str],
    aoi_ref_lookup: dict[str, str],
    output_container: str,
) -> dict[str, Any]:
    """Build a single post_process_imagery activity payload."""
    return {
        "download_result": dl,
        "aoi_ref": aoi_ref_lookup.get(dl.get("aoi_feature_name", "")),
        "project_name": ctx["project_name"],
        "timestamp": ctx["timestamp"],
        "target_crs": inp.get("target_crs", "EPSG:4326"),
        "enable_clipping": inp.get("enable_clipping", True),
        "enable_reprojection": inp.get("enable_reprojection", True),
        "output_container": output_container,
        "square_frame": inp.get("square_frame", True),
        "frame_padding_pct": inp.get("frame_padding_pct", 10.0),
    }

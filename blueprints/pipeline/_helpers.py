"""Pipeline helpers: constants, validation, response shaping.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import re
from typing import Any
from urllib.parse import urlparse

from treesight.constants import DEFAULT_PROVIDER, MAX_KML_FILE_SIZE_BYTES
from treesight.errors import ContractError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


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


def _reshape_output(output: dict[str, Any] | str) -> dict[str, Any]:
    """Reshape PipelineSummary to the diagnostics contract (§4.3).

    The Durable Functions SDK sometimes returns output as a JSON string
    instead of a parsed dict — handle both cases.
    """
    if isinstance(output, str):
        import json

        try:
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return {"status": "unknown", "message": output}
    if not isinstance(output, dict):
        return {"status": "unknown", "message": str(output)}
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
        # Intentional: use first AOI's bbox only. Enrichment (weather, NDVI)
        # targets a single representative location, not the union of all AOIs.
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


def _collect_per_aoi_coords(
    aois: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract per-AOI coordinate data for per-AOI enrichment.

    Returns a list of dicts, one per AOI, each containing:
    - ``name``: the feature name
    - ``coords``: the exterior coordinates (or bbox-derived ring)
    - ``area_ha``: area in hectares
    """
    result: list[dict[str, Any]] = []
    for aoi in aois:
        coords = aoi.get("exterior_coords", [])
        if not coords:
            bb = aoi.get("bbox") or aoi.get("buffered_bbox")
            if bb and len(bb) == 4:
                min_lon, min_lat, max_lon, max_lat = bb
                coords = [
                    [min_lon, min_lat],
                    [max_lon, min_lat],
                    [max_lon, max_lat],
                    [min_lon, max_lat],
                    [min_lon, min_lat],
                ]
        if coords:
            result.append(
                {
                    "name": aoi.get("feature_name", ""),
                    "coords": coords,
                    "area_ha": aoi.get("area_ha", 0.0),
                }
            )
    return result


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


def _split_batch_routing(
    ready: list[dict[str, Any]],
    aoi_area_by_name: dict[str, float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split ready outcomes into serverless vs Azure Batch tiers.

    Returns ``(serverless_ready, batch_ready)``.
    """
    from treesight.pipeline.batch import needs_batch_fallback

    serverless: list[dict[str, Any]] = []
    batch: list[dict[str, Any]] = []
    for outcome in ready:
        area = aoi_area_by_name.get(outcome.get("aoi_feature_name", ""), 0.0)
        if needs_batch_fallback(area):
            batch.append(outcome)
        else:
            serverless.append(outcome)
    return serverless, batch


def _acq_payload(
    ref: dict[str, str],
    inp: dict[str, Any],
    composite: bool,
) -> dict[str, Any]:
    """Build a single acquisition activity payload from a claim ref."""
    base: dict[str, Any] = {
        "aoi_ref": ref["ref"],
        "provider_name": inp.get("provider_name", DEFAULT_PROVIDER),
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
        "provider_name": inp.get("provider_name", DEFAULT_PROVIDER),
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
        "provider_name": inp.get("provider_name", DEFAULT_PROVIDER),
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


# ---------------------------------------------------------------------------
# Progressive delivery: sub-orchestrator result aggregation (#585)
# ---------------------------------------------------------------------------


def _aggregate_aoi_results(
    aoi_results: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge per-AOI sub-orchestrator results into acquisition and fulfilment summaries.

    Returns ``(acquisition_summary, fulfilment_summary)`` matching the shapes
    expected by ``build_pipeline_summary``.
    """
    acq: dict[str, Any] = {"imagery_outcomes": [], "ready_count": 0, "failed_count": 0}
    ful: dict[str, Any] = {
        "download_results": [],
        "downloads_completed": 0,
        "downloads_succeeded": 0,
        "downloads_failed": 0,
        "batch_submitted": 0,
        "batch_succeeded": 0,
        "batch_failed": 0,
        "post_process_results": [],
        "pp_completed": 0,
        "pp_clipped": 0,
        "pp_reprojected": 0,
        "pp_failed": 0,
    }

    for r in aoi_results:
        a = r.get("acquisition", {})
        acq["ready_count"] += a.get("ready_count", 0)
        acq["failed_count"] += a.get("failed_count", 0)
        acq["imagery_outcomes"].extend(a.get("imagery_outcomes", []))

        f = r.get("fulfilment", {})
        succeeded = f.get("downloads_succeeded", 0)
        failed = f.get("downloads_failed", 0)
        ful["download_results"].extend(f.get("download_results", []))
        ful["downloads_completed"] += f.get("downloads_completed", 0)
        ful["downloads_succeeded"] += succeeded
        ful["downloads_failed"] += failed
        ful["batch_submitted"] += f.get("batch_submitted", 0)
        ful["batch_succeeded"] += f.get("batch_succeeded", 0)
        ful["batch_failed"] += f.get("batch_failed", 0)
        ful["post_process_results"].extend(f.get("pp_results", []))
        ful["pp_completed"] += f.get("pp_completed", 0)
        ful["pp_clipped"] += f.get("pp_clipped", 0)
        ful["pp_reprojected"] += f.get("pp_reprojected", 0)
        ful["pp_failed"] += f.get("pp_failed", 0)

    return acq, ful

"""Pipeline helpers: constants, validation, response shaping.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from treesight.config import MAX_JOB_DURATION_MINUTES
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

_ACTIVE_RUNTIME_STATUSES = {"running", "pending"}
_PHASE_RANK = {
    "queued": 0,
    "submit": 0,
    "ingestion": 1,
    "acquisition": 2,
    "per_aoi_pipeline": 2,
    "fulfilment": 3,
    "enrichment": 4,
    "complete": 5,
}
_HISTORY_PHASE_HINTS = {
    "parse_kml": ("ingestion", "parsing_kml"),
    "load_offloaded_features": ("ingestion", "parsing_kml"),
    "prepare_aoi": ("ingestion", "preparing_aois"),
    "store_aoi_claims": ("ingestion", "storing_claims"),
    "write_metadata": ("ingestion", "writing_metadata"),
    "acquire_composite": ("acquisition", "searching"),
    "acquire_imagery": ("acquisition", "searching"),
    "poll_order": ("acquisition", "polling"),
    "aoi_pipeline": ("acquisition", "per_aoi_pipeline"),
    "download_assets": ("fulfilment", "downloading"),
    "batch_submit_downloads": ("fulfilment", "batch_submit"),
    "poll_batch_downloads": ("fulfilment", "batch_polling"),
    "post_process": ("fulfilment", "post_processing"),
    "enrich_data_sources": ("enrichment", "data_sources_and_imagery"),
    "enrich_imagery": ("enrichment", "data_sources_and_imagery"),
    "enrich_single_aoi_step": ("enrichment", "per_aoi"),
    "enrich_finalize": ("enrichment", "finalizing"),
}


def _coerce_custom_status(custom_status: Any) -> dict[str, Any] | None:
    if custom_status is None:
        return None
    if isinstance(custom_status, dict):
        return dict(custom_status)
    if isinstance(custom_status, str):
        try:
            parsed = json.loads(custom_status)
        except (json.JSONDecodeError, TypeError):
            return {"raw": custom_status}
        return parsed if isinstance(parsed, dict) else {"raw": custom_status}
    return {"raw": str(custom_status)}


def _history_attr(event: Any, *names: str) -> Any:
    for name in names:
        if isinstance(event, dict) and name in event:
            return event[name]
        if hasattr(event, name):
            return getattr(event, name)
    return None


def _infer_phase_from_history(history: list[Any] | None) -> tuple[str, str] | None:
    if not history:
        return None
    for event in reversed(history):
        name = _history_attr(
            event,
            "FunctionName",
            "functionName",
            "Name",
            "name",
            "TaskName",
            "taskName",
        )
        if not isinstance(name, str):
            continue
        hint = _HISTORY_PHASE_HINTS.get(name)
        if hint:
            return hint
    return None


def _is_stalled_runtime(runtime_status: str | None, last_updated_time: datetime | None) -> bool:
    if not runtime_status or not last_updated_time:
        return False
    if runtime_status.strip().lower() not in _ACTIVE_RUNTIME_STATUSES:
        return False
    now = datetime.now(UTC)
    cutoff = timedelta(minutes=MAX_JOB_DURATION_MINUTES)
    last_updated = last_updated_time
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=UTC)
    return now - last_updated >= cutoff


def _merge_history_hint(
    custom_status: dict[str, Any] | None,
    history: list[Any] | None,
) -> dict[str, Any] | None:
    inferred = _infer_phase_from_history(history)
    if not inferred:
        return custom_status

    phase, step = inferred
    merged = dict(custom_status or {})
    current_phase = str(merged.get("phase") or "").strip().lower()
    if _PHASE_RANK.get(phase, 0) >= _PHASE_RANK.get(current_phase, 0):
        merged["phase"] = phase
        merged["step"] = step
        merged.setdefault("source", "durable_history")
    return merged


def _normalize_runtime_status_payload(status: Any) -> tuple[str | None, dict[str, Any] | None]:
    runtime_status = status.runtime_status.value if status.runtime_status else None
    custom_status = _coerce_custom_status(status.custom_status)
    custom_status = _merge_history_hint(custom_status, getattr(status, "history", None))
    if _is_stalled_runtime(runtime_status, status.last_updated_time):
        custom_status = dict(custom_status or {})
        custom_status["stalled"] = True
        # Fallback only — preserve any phase/step already set by the history
        # hint (which is more accurate than a bare "queued"). setdefault is
        # a no-op when the key is present, so a self-referential default
        # would be misleading; use plain literals.
        custom_status.setdefault("phase", "queued")
        custom_status.setdefault("step", "no_recent_updates")
        runtime_status = "Stalled"
    return runtime_status, custom_status


def _durable_status_payload(status: Any) -> dict[str, Any]:
    runtime_status, custom_status = _normalize_runtime_status_payload(status)
    return {
        "instanceId": status.instance_id,
        "name": status.name,
        "runtimeStatus": runtime_status,
        "createdTime": str(status.created_time),
        "lastUpdatedTime": str(status.last_updated_time),
        "customStatus": custom_status,
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

    Assigns a ``cluster`` label so downstream consumers (enrichment, spatial
    clustering #581) can identify spatially proximate AOIs.

    Returns a list of dicts, one per AOI, each containing:
    - ``name``: the feature name
    - ``coords``: the exterior coordinates (or bbox-derived ring)
    - ``area_ha``: area in hectares
    - ``cluster``: zero-based cluster index from spatial grouping
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

    # Assign spatial cluster labels (#581)
    if len(result) > 1:
        from treesight.geo import cluster_aois

        clusters = cluster_aois(result)
        for cluster_idx, group in enumerate(clusters):
            for entry in group:
                entry["cluster"] = cluster_idx
    elif result:
        result[0]["cluster"] = 0

    return result


def _build_order_lookups(
    orders: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Build asset URL and order metadata lookup dicts from order results.

    Orders that have no ``order_id`` are silently skipped; they cannot be
    looked up and inserting them under the empty-string key would cause all
    ID-less orders to collide and overwrite each other.
    """
    asset_urls: dict[str, str] = {
        o["order_id"]: o.get("asset_url", "") for o in orders if o.get("order_id")
    }
    order_meta: dict[str, dict[str, str]] = {
        o["order_id"]: {
            "role": o.get("role", ""),
            "collection": o.get("collection", ""),
        }
        for o in orders
        if o.get("order_id")
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
        ful["post_process_results"].extend(f.get("post_process_results", []))
        ful["pp_completed"] += f.get("pp_completed", 0)
        ful["pp_clipped"] += f.get("pp_clipped", 0)
        ful["pp_reprojected"] += f.get("pp_reprojected", 0)
        ful["pp_failed"] += f.get("pp_failed", 0)

    return acq, ful

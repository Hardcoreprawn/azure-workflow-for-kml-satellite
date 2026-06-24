"""Orchestrator activity payload builders and AOI coordinate helpers.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

from typing import Any

from treesight.constants import DEFAULT_PROVIDER


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

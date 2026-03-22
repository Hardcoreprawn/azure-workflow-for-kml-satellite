"""Enrichment orchestrator — runs weather, flood, fire, mosaic, NDVI, and stores manifest."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from treesight.log import log_phase
from treesight.pipeline.enrichment.aoi_metrics import (
    compute_aoi_metrics,
    compute_multi_aoi_summary,
)
from treesight.pipeline.enrichment.change_detection import detect_changes
from treesight.pipeline.enrichment.fire import fetch_fire_hotspots
from treesight.pipeline.enrichment.flood import fetch_flood_events
from treesight.pipeline.enrichment.frames import build_frame_plan
from treesight.pipeline.enrichment.mosaic import _coords_to_bbox, register_mosaic
from treesight.pipeline.enrichment.ndvi import compute_ndvi, fetch_ndvi_stat
from treesight.pipeline.enrichment.weather import (
    aggregate_weather_monthly,
    fetch_weather,
)
from treesight.storage.client import BlobStorageClient

logger = logging.getLogger(__name__)


def run_enrichment(
    coords: list[list[float]],
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
    aoi_list: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run full enrichment pipeline — the main entry point.

    Fetches weather, registers mosaics, samples NDVI, and stores everything
    in blob storage as a single timelapse_payload.json manifest.

    Parameters
    ----------
    aoi_list : list of dict, optional
        Per-AOI data dicts (from AOI.model_dump()).  When supplied the
        manifest will include ``per_aoi_metrics`` with quantitative
        statistics for each AOI individually.

    Returns the enrichment results dict.
    """
    start = time.monotonic()
    bbox = _coords_to_bbox(coords)
    frame_plan = build_frame_plan(coords)

    # Centroid for weather
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    center_lat = round((min(lats) + max(lats)) / 2, 4)
    center_lon = round((min(lons) + max(lons)) / 2, 4)

    results: dict[str, Any] = {
        "frame_plan": frame_plan,
        "coords": coords,
        "bbox": bbox,
        "center": {"lat": center_lat, "lon": center_lon},
    }

    # 1. Weather data
    log_phase("enrichment", "weather_start", lat=center_lat, lon=center_lon)
    first_date = frame_plan[0]["start"]
    last_date = frame_plan[-1]["end"]
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    end_date = min(last_date, today)

    weather = fetch_weather(center_lat, center_lon, first_date, end_date)
    if weather:
        results["weather_daily"] = weather
        results["weather_monthly"] = aggregate_weather_monthly(weather)
        log_phase(
            "enrichment",
            "weather_done",
            days=len(weather.get("dates", [])),
        )
    else:
        results["weather_daily"] = None
        results["weather_monthly"] = None
        log_phase("enrichment", "weather_failed")

    # 1b. Flood event detection
    log_phase("enrichment", "flood_start")
    flood_data = fetch_flood_events(bbox, center_lat, center_lon)
    results["flood_events"] = flood_data
    log_phase("enrichment", "flood_done", source=flood_data["source"], count=flood_data["count"])

    # 1c. Fire hotspot detection
    log_phase("enrichment", "fire_start")
    fire_data = fetch_fire_hotspots(bbox)
    results["fire_hotspots"] = fire_data
    log_phase("enrichment", "fire_done", source=fire_data["source"], count=fire_data["count"])

    # 2. Mosaic registration
    log_phase("enrichment", "mosaic_start", frames=len(frame_plan))
    http_client = httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    search_ids: list[str | None] = []
    ndvi_search_ids: list[str | None] = []

    for f in frame_plan:
        extra: list[dict[str, Any]] = (
            [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}]
            if f["collection"] == "sentinel-2-l2a"
            else []
        )
        sid = register_mosaic(
            f["collection"],
            f["start"],
            f["end"],
            bbox,
            extra,
            http_client,
        )
        search_ids.append(sid)

        # S2 search ID for NDVI on NAIP frames
        if f["is_naip"]:
            s2_sid = register_mosaic(
                "sentinel-2-l2a",
                f["start"],
                f["end"],
                bbox,
                [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}],
                http_client,
            )
            ndvi_search_ids.append(s2_sid)
        else:
            ndvi_search_ids.append(sid)

    results["search_ids"] = search_ids
    results["ndvi_search_ids"] = ndvi_search_ids
    log_phase(
        "enrichment",
        "mosaic_done",
        registered=sum(1 for s in search_ids if s),
        total=len(search_ids),
    )

    # 3. NDVI computation
    #    Try proper COG band-math first (accurate, produces GeoTIFFs).
    #    Fall back to PC tile sampling (fast, PNG-based approximation).
    flat_bbox = [bbox[0][0], bbox[0][1], bbox[2][0], bbox[2][1]]
    log_phase("enrichment", "ndvi_start", frames=len(frame_plan))
    ndvi_stats: list[dict[str, float] | None] = []
    ndvi_raster_paths: list[str | None] = []

    for i, f in enumerate(frame_plan):
        # Only compute NDVI for Sentinel-2 frames (NAIP lacks B08)
        if f["collection"] == "sentinel-2-l2a" or f["is_naip"]:
            # Try COG-based computation
            cog_result = compute_ndvi(flat_bbox, f["start"], f["end"])
            if cog_result is not None:
                geotiff_bytes = cog_result.pop("geotiff_bytes", None)
                ndvi_stats.append(cog_result)
                # Store NDVI raster for change detection
                if geotiff_bytes:
                    raster_path = (
                        f"enrichment/{project_name}/{timestamp}/ndvi/{f['year']}_{f['season']}.tif"
                    )
                    storage.upload_bytes(
                        output_container,
                        raster_path,
                        geotiff_bytes,
                        content_type="image/tiff",
                    )
                    ndvi_raster_paths.append(raster_path)
                else:
                    ndvi_raster_paths.append(None)
                continue

        # Fallback: tile-based sampling
        nsid = ndvi_search_ids[i] if i < len(ndvi_search_ids) else None
        if nsid:
            stat = fetch_ndvi_stat(nsid, coords, http_client)
            ndvi_stats.append(stat)
        else:
            ndvi_stats.append(None)
        ndvi_raster_paths.append(None)

    results["ndvi_stats"] = ndvi_stats
    results["ndvi_raster_paths"] = ndvi_raster_paths
    ndvi_count = sum(1 for s in ndvi_stats if s)
    cog_count = sum(1 for s in ndvi_stats if s and s.get("scene_id"))
    log_phase(
        "enrichment",
        "ndvi_done",
        sampled=ndvi_count,
        cog_computed=cog_count,
        total=len(ndvi_stats),
    )

    # 4. Build labelled frame metadata (mirrors frontend framesMeta)
    for i, f in enumerate(frame_plan):
        f["search_id"] = search_ids[i]
        f["ndvi_search_id"] = ndvi_search_ids[i]
        f["ndvi_stat"] = ndvi_stats[i]
        f["ndvi_raster_path"] = ndvi_raster_paths[i] if i < len(ndvi_raster_paths) else None
        season_key = f["season"]
        year = f["year"]
        if f["is_naip"]:
            f["label"] = f"NAIP Summer {year}"
        else:
            f["label"] = f"{season_key.capitalize()} {year}"
        res = "0.6" if f["is_naip"] and year > 2014 else "1.0" if f["is_naip"] else "10"
        src = "NAIP © USDA" if f["is_naip"] else "Sentinel-2 L2A"
        f["info"] = f"{src} | {res} m/px | {f['start']} → {f['end']}"

    # 5. Change detection — compare same-season NDVI rasters year-over-year
    if any(ndvi_raster_paths):
        log_phase("enrichment", "change_detection_start")
        change_results = detect_changes(
            frame_plan=frame_plan,
            ndvi_raster_paths=ndvi_raster_paths,
            output_container=output_container,
            project_name=project_name,
            timestamp=timestamp,
            storage=storage,
        )
        results["change_detection"] = change_results
        log_phase(
            "enrichment",
            "change_detection_done",
            comparisons=change_results["summary"]["comparisons"],
            trajectory=change_results["summary"].get("trajectory"),
        )
    else:
        results["change_detection"] = {"season_changes": [], "summary": {}}

    # 6. Per-AOI quantitative metrics (when AOI list is provided)
    #
    # NOTE: Geometry metrics (area, perimeter, compactness, bbox) are truly
    # per-AOI.  NDVI/change/weather are currently derived from the union
    # bounding box — accurate for single-AOI KMLs, shared across AOIs for
    # multi-AOI KMLs.  data_scope="per_aoi" vs "union" is set accordingly.
    # Per-AOI NDVI/change computation is planned for a follow-up.
    if aoi_list is not None:
        data_scope = "per_aoi" if len(aoi_list) <= 1 else "union"
        log_phase("enrichment", "aoi_metrics_start", aoi_count=len(aoi_list))
        per_aoi: list[dict[str, Any]] = []
        for aoi_data in aoi_list:
            m = compute_aoi_metrics(
                aoi_data=aoi_data,
                ndvi_stats=ndvi_stats,
                weather_daily=results.get("weather_daily"),
                change_detection=results.get("change_detection"),
            )
            m["ndvi_data_scope"] = data_scope
            per_aoi.append(m)
        results["per_aoi_metrics"] = per_aoi
        results["multi_aoi_summary"] = compute_multi_aoi_summary(per_aoi)
        log_phase("enrichment", "aoi_metrics_done", aoi_count=len(per_aoi))

    # 7. Store manifest
    duration = time.monotonic() - start
    results["enrichment_duration_seconds"] = round(duration, 1)
    results["enriched_at"] = datetime.now(UTC).isoformat()

    manifest_path = f"enrichment/{project_name}/{timestamp}/timelapse_payload.json"
    storage.upload_json(output_container, manifest_path, results)
    results["manifest_path"] = manifest_path

    log_phase(
        "enrichment",
        "complete",
        duration=f"{duration:.1f}s",
        manifest=manifest_path,
        frames=len(frame_plan),
        ndvi_sampled=ndvi_count,
        weather="yes" if weather else "no",
    )

    return results

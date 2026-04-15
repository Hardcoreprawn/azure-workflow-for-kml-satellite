"""Enrichment orchestrator — runs weather, flood, fire, mosaic, NDVI, and stores manifest."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from treesight.constants import (
    DEFAULT_ENRICHMENT_CONCURRENCY,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    EUDR_CUTOFF_DATE,
)
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


# ── Phase functions ───────────────────────────────────────────


def _run_weather_phase(
    center_lat: float,
    center_lon: float,
    first_date: str,
    last_date: str,
    results: dict[str, Any],
) -> None:
    """Phase 1: fetch daily weather data and aggregate monthly summaries."""
    log_phase("enrichment", "weather_start", lat=center_lat, lon=center_lon)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    end_date = min(last_date, today)

    weather = fetch_weather(center_lat, center_lon, first_date, end_date)
    if weather:
        results["weather_daily"] = weather
        results["weather_monthly"] = aggregate_weather_monthly(weather)
        log_phase("enrichment", "weather_done", days=len(weather.get("dates", [])))
    else:
        results["weather_daily"] = None
        results["weather_monthly"] = None
        log_phase("enrichment", "weather_failed")


def _run_flood_fire_phase(
    bbox: list[list[float]],
    center_lat: float,
    center_lon: float,
    results: dict[str, Any],
) -> None:
    """Phase 1b/1c: flood event detection and fire hotspot detection."""
    log_phase("enrichment", "flood_start")
    flood_data = fetch_flood_events(bbox, center_lat, center_lon)
    results["flood_events"] = flood_data
    log_phase("enrichment", "flood_done", source=flood_data["source"], count=flood_data["count"])

    log_phase("enrichment", "fire_start")
    fire_data = fetch_fire_hotspots(bbox)
    results["fire_hotspots"] = fire_data
    log_phase("enrichment", "fire_done", source=fire_data["source"], count=fire_data["count"])


def _run_eudr_phase(
    bbox: list[list[float]],
    center_lat: float,
    center_lon: float,
    results: dict[str, Any],
) -> None:
    """Phase 1d: EUDR-specific enrichments (WorldCover + WDPA)."""
    from treesight.pipeline.eudr import check_wdpa_overlap, query_worldcover

    flat_bbox_eudr = [bbox[0][0], bbox[0][1], bbox[2][0], bbox[2][1]]

    log_phase("enrichment", "worldcover_start")
    worldcover = query_worldcover(flat_bbox_eudr)
    results["worldcover"] = worldcover
    log_phase("enrichment", "worldcover_done", available=worldcover.get("available", False))

    log_phase("enrichment", "wdpa_start")
    wdpa = check_wdpa_overlap(center_lon, center_lat)
    results["wdpa"] = wdpa
    log_phase(
        "enrichment",
        "wdpa_done",
        checked=wdpa.get("checked", False),
        protected=wdpa.get("is_protected", False),
    )


def _run_mosaic_ndvi_phase(
    bbox: list[list[float]],
    coords: list[list[float]],
    frame_plan: list[dict[str, Any]],
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
    results: dict[str, Any],
) -> tuple[list[dict[str, Any] | None], list[str | None]]:
    """Phase 2/3: mosaic registration + NDVI computation (COG or tile fallback)."""
    # 2. Mosaic registration (parallel — each frame is independent)
    log_phase("enrichment", "mosaic_start", frames=len(frame_plan))
    search_ids: list[str | None] = [None] * len(frame_plan)
    ndvi_search_ids: list[str | None] = [None] * len(frame_plan)

    def _register_one(idx: int, f: dict[str, Any]) -> tuple[int, str | None, str | None]:
        extra: list[dict[str, Any]] = (
            [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}]
            if f["collection"] == "sentinel-2-l2a"
            else []
        )
        with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as cl:
            sid = register_mosaic(f["collection"], f["start"], f["end"], bbox, extra, cl)
            nsid = sid
            if f["is_naip"]:
                nsid = register_mosaic(
                    "sentinel-2-l2a",
                    f["start"],
                    f["end"],
                    bbox,
                    [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}],
                    cl,
                )
        return idx, sid, nsid

    with ThreadPoolExecutor(max_workers=DEFAULT_ENRICHMENT_CONCURRENCY) as pool:
        futures = [pool.submit(_register_one, i, f) for i, f in enumerate(frame_plan)]
        for fut in as_completed(futures):
            try:
                idx, sid, nsid = fut.result()
            except Exception:
                logger.warning("mosaic registration failed for one frame", exc_info=True)
                continue
            search_ids[idx] = sid
            ndvi_search_ids[idx] = nsid

    results["search_ids"] = search_ids
    results["ndvi_search_ids"] = ndvi_search_ids
    log_phase(
        "enrichment",
        "mosaic_done",
        registered=sum(1 for s in search_ids if s),
        total=len(search_ids),
    )

    # 3. NDVI computation (parallel — each frame is independent I/O)
    flat_bbox = [bbox[0][0], bbox[0][1], bbox[2][0], bbox[2][1]]
    log_phase("enrichment", "ndvi_start", frames=len(frame_plan))
    ndvi_stats: list[dict[str, float] | None] = [None] * len(frame_plan)
    ndvi_raster_paths: list[str | None] = [None] * len(frame_plan)

    def _compute_one_ndvi(
        idx: int, f: dict[str, Any]
    ) -> tuple[int, dict[str, Any] | None, str | None]:
        if f["collection"] == "sentinel-2-l2a" or f["is_naip"]:
            cog_result = compute_ndvi(flat_bbox, f["start"], f["end"])
            if cog_result is not None:
                geotiff_bytes = cog_result.pop("geotiff_bytes", None)
                raster_path = None
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
                return idx, cog_result, raster_path

        # Fallback: tile-based sampling
        nsid = ndvi_search_ids[idx]
        if nsid:
            with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as cl:
                stat = fetch_ndvi_stat(nsid, coords, cl)
            return idx, stat, None
        return idx, None, None

    with ThreadPoolExecutor(max_workers=DEFAULT_ENRICHMENT_CONCURRENCY) as pool:
        futures = [pool.submit(_compute_one_ndvi, i, f) for i, f in enumerate(frame_plan)]
        for fut in as_completed(futures):
            try:
                idx, stat, rpath = fut.result()
            except Exception:
                logger.warning("NDVI computation failed for one frame", exc_info=True)
                continue
            ndvi_stats[idx] = stat
            ndvi_raster_paths[idx] = rpath

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

    return ndvi_stats, ndvi_raster_paths


def _run_change_detection_phase(
    frame_plan: list[dict[str, Any]],
    ndvi_raster_paths: list[str | None],
    output_container: str,
    project_name: str,
    timestamp: str,
    storage: BlobStorageClient,
    results: dict[str, Any],
) -> None:
    """Phase 5: compare same-season NDVI rasters year-over-year."""
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


def _run_aoi_metrics_phase(
    aoi_list: list[dict[str, Any]],
    ndvi_stats: list[dict[str, float] | None],
    results: dict[str, Any],
) -> None:
    """Phase 6: per-AOI quantitative metrics."""
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


# ── Per-AOI enrichment ────────────────────────────────────────


def _enrich_single_aoi(
    aoi_entry: dict[str, Any],
    *,
    date_start: str | None,
    date_end: str | None,
    cadence: str,
    max_history_years: int | None,
    eudr_mode: bool,
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
) -> dict[str, Any]:
    """Run enrichment for a single AOI and return its results dict."""
    aoi_name = aoi_entry.get("name", "")
    coords = aoi_entry["coords"]

    bbox = _coords_to_bbox(coords)
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    center_lat = round((min(lats) + max(lats)) / 2, 4)
    center_lon = round((min(lons) + max(lons)) / 2, 4)

    frame_plan = build_frame_plan(
        coords,
        date_start=date_start,
        date_end=date_end,
        cadence=cadence,
        max_history_years=max_history_years,
    )

    result: dict[str, Any] = {
        "name": aoi_name,
        "coords": coords,
        "bbox": bbox,
        "center": {"lat": center_lat, "lon": center_lon},
        "frame_plan": frame_plan,
        "area_ha": aoi_entry.get("area_ha", 0.0),
    }

    if not frame_plan:
        return result

    first_date = frame_plan[0]["start"]
    last_date = frame_plan[-1]["end"]
    _run_weather_phase(center_lat, center_lon, first_date, last_date, result)
    _run_flood_fire_phase(bbox, center_lat, center_lon, result)

    if eudr_mode:
        _run_eudr_phase(bbox, center_lat, center_lon, result)

    _ndvi_stats, ndvi_raster_paths = _run_mosaic_ndvi_phase(
        bbox,
        coords,
        frame_plan,
        project_name,
        timestamp,
        output_container,
        storage,
        result,
    )

    _run_change_detection_phase(
        frame_plan,
        ndvi_raster_paths,
        output_container,
        project_name,
        timestamp,
        storage,
        result,
    )

    # Deforestation-free determination (#603)
    if eudr_mode:
        from treesight.pipeline.enrichment.determination import (
            determine_deforestation_free,
        )

        result["determination"] = determine_deforestation_free(result)

    return result


# ── Main orchestrator ─────────────────────────────────────────


def run_enrichment(
    coords: list[list[float]],
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
    aoi_list: list[dict[str, Any]] | None = None,
    *,
    per_aoi_coords: list[dict[str, Any]] | None = None,
    eudr_mode: bool = False,
    date_start: str | None = None,
    date_end: str | None = None,
    cadence: str = "maximum",
    max_history_years: int | None = None,
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
    eudr_mode : bool
        When True, constrains frame plan to post-2020 (EUDR cutoff) and
        adds ``eudr`` metadata to the manifest.
    date_start, date_end : str, optional
        ISO date strings to filter the frame plan.  ``eudr_mode`` sets
        ``date_start`` to ``2021-01-01`` if not already supplied.

    Returns the enrichment results dict.
    """
    start = time.monotonic()
    bbox = _coords_to_bbox(coords)

    # EUDR mode: default to post-cutoff baseline
    if eudr_mode and not date_start:
        cutoff = date.fromisoformat(EUDR_CUTOFF_DATE)
        date_start = (cutoff + timedelta(days=1)).isoformat()

    frame_plan = build_frame_plan(
        coords,
        date_start=date_start,
        date_end=date_end,
        cadence=cadence,
        max_history_years=max_history_years,
    )

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

    if not frame_plan:
        logger.warning("No frames matched date filters — returning partial manifest")
        results["enriched_at"] = datetime.now(UTC).isoformat()
        if eudr_mode:
            results["eudr_mode"] = True
            results["eudr_date_start"] = date_start
        return results

    # 1. Weather data
    first_date = frame_plan[0]["start"]
    last_date = frame_plan[-1]["end"]
    _run_weather_phase(center_lat, center_lon, first_date, last_date, results)

    # 1b/1c. Flood + fire
    _run_flood_fire_phase(bbox, center_lat, center_lon, results)

    # 1d. EUDR-specific enrichments (WorldCover + WDPA)
    if eudr_mode:
        _run_eudr_phase(bbox, center_lat, center_lon, results)

    # 2/3. Mosaic registration + NDVI computation
    ndvi_stats, ndvi_raster_paths = _run_mosaic_ndvi_phase(
        bbox,
        coords,
        frame_plan,
        project_name,
        timestamp,
        output_container,
        storage,
        results,
    )

    # 5. Change detection
    _run_change_detection_phase(
        frame_plan,
        ndvi_raster_paths,
        output_container,
        project_name,
        timestamp,
        storage,
        results,
    )

    # 6. Per-AOI quantitative metrics
    if aoi_list is not None:
        _run_aoi_metrics_phase(aoi_list, ndvi_stats, results)

    # 6b. Per-AOI enrichment — each AOI gets its own weather, NDVI, change detection
    if per_aoi_coords and len(per_aoi_coords) > 1:
        log_phase("enrichment", "per_aoi_start", aoi_count=len(per_aoi_coords))
        per_aoi_enrichment: list[dict[str, Any]] = []
        for entry in per_aoi_coords:
            try:
                aoi_result = _enrich_single_aoi(
                    entry,
                    date_start=date_start,
                    date_end=date_end,
                    cadence=cadence,
                    max_history_years=max_history_years,
                    eudr_mode=eudr_mode,
                    project_name=project_name,
                    timestamp=timestamp,
                    output_container=output_container,
                    storage=storage,
                )
                per_aoi_enrichment.append(aoi_result)
            except Exception:
                logger.warning(
                    "Per-AOI enrichment failed for %s — skipping",
                    entry.get("name", "?"),
                    exc_info=True,
                )
                per_aoi_enrichment.append(
                    {"name": entry.get("name", ""), "error": "enrichment_failed"}
                )
        results["per_aoi_enrichment"] = per_aoi_enrichment
        log_phase(
            "enrichment",
            "per_aoi_done",
            total=len(per_aoi_enrichment),
            succeeded=sum(1 for r in per_aoi_enrichment if "error" not in r),
        )

    # 7. Store manifest
    duration = time.monotonic() - start
    results["enrichment_duration_seconds"] = round(duration, 1)
    results["enriched_at"] = datetime.now(UTC).isoformat()
    if eudr_mode:
        results["eudr_mode"] = True
        results["eudr_date_start"] = date_start

        # Overall deforestation-free determination (#603)
        from treesight.pipeline.enrichment.determination import (
            determine_deforestation_free,
        )

        results["determination"] = determine_deforestation_free(results)

    manifest_path = f"enrichment/{project_name}/{timestamp}/timelapse_payload.json"
    storage.upload_json(output_container, manifest_path, results)
    results["manifest_path"] = manifest_path

    log_phase(
        "enrichment",
        "complete",
        duration=f"{duration:.1f}s",
        manifest=manifest_path,
        frames=len(frame_plan),
        ndvi_sampled=sum(1 for s in ndvi_stats if s),
        weather="yes" if results.get("weather_daily") else "no",
    )

    return results

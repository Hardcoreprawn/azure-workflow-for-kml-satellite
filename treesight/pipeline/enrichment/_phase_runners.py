"""Per-data-source enrichment phase runners.

Weather, flood/fire, EUDR datasets, Landsat baseline, mosaic/NDVI, change
detection, and per-AOI quantitative metrics — extracted from runner.py
(#1292). Pure phase functions called by the orchestration entry points in
runner.py (run_enrichment, enrich_data_sources, enrich_imagery,
_enrich_single_aoi). No behavior change from the extraction.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

import httpx

from treesight.constants import (
    COLLECTION_DISPLAY_GSD_M,
    DEFAULT_ENRICHMENT_CONCURRENCY,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
)
from treesight.log import log_phase
from treesight.pipeline.enrichment.aoi_metrics import (
    compute_aoi_metrics,
    compute_multi_aoi_summary,
)
from treesight.pipeline.enrichment.change_detection import detect_changes
from treesight.pipeline.enrichment.fire import fetch_fire_hotspots
from treesight.pipeline.enrichment.flood import fetch_flood_events
from treesight.pipeline.enrichment.mosaic import register_mosaic
from treesight.pipeline.enrichment.ndvi import (
    compute_landsat_ndvi,
    compute_ndvi,
    fetch_ndvi_stat,
)
from treesight.pipeline.enrichment.resource_accumulator import ResourceAccumulator
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
    acc: ResourceAccumulator | None = None,
) -> None:
    """Phase 1: fetch daily weather data and aggregate monthly summaries."""
    t0 = time.monotonic()
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

    if acc:
        acc.add_source("open-meteo")
        acc.add_api_call("open_meteo")
        acc.record_phase_duration("weather", time.monotonic() - t0)


def _run_flood_fire_phase(
    bbox: list[list[float]],
    center_lat: float,
    center_lon: float,
    results: dict[str, Any],
    acc: ResourceAccumulator | None = None,
) -> None:
    """Phase 1b/1c: flood event detection and fire hotspot detection."""
    t0 = time.monotonic()
    log_phase("enrichment", "flood_start")
    flood_data = fetch_flood_events(bbox, center_lat, center_lon)
    results["flood_events"] = flood_data
    log_phase("enrichment", "flood_done", source=flood_data["source"], count=flood_data["count"])

    log_phase("enrichment", "fire_start")
    fire_data = fetch_fire_hotspots(bbox)
    results["fire_hotspots"] = fire_data
    log_phase("enrichment", "fire_done", source=fire_data["source"], count=fire_data["count"])

    if acc:
        acc.add_source("gfd-flood")
        acc.add_source("firms-fire")
        acc.add_api_call("gfd")
        acc.add_api_call("firms")
        acc.record_phase_duration("flood_fire", time.monotonic() - t0)


def _run_eudr_phase(
    bbox: list[list[float]],
    center_lat: float,
    center_lon: float,
    results: dict[str, Any],
    acc: ResourceAccumulator | None = None,
) -> None:
    """Phase 1d: EUDR-specific enrichments (WorldCover + WDPA + IO LULC + ALOS FNF)."""
    from treesight.pipeline.eudr import (
        check_wdpa_overlap,
        query_alos_fnf,
        query_lulc_annual,
        query_worldcover,
    )

    t0 = time.monotonic()
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

    log_phase("enrichment", "lulc_annual_start")
    lulc = query_lulc_annual(flat_bbox_eudr)
    results["lulc_annual"] = lulc
    log_phase("enrichment", "lulc_annual_done", available=lulc.get("available", False))

    log_phase("enrichment", "alos_fnf_start")
    alos = query_alos_fnf(flat_bbox_eudr)
    results["alos_fnf"] = alos
    log_phase("enrichment", "alos_fnf_done", available=alos.get("available", False))

    # Landsat historical NDVI baseline (#609)
    _run_landsat_baseline(flat_bbox_eudr, results)

    if acc:
        acc.add_source("esa-worldcover")
        acc.add_source("wdpa")
        acc.add_source("io-lulc")
        acc.add_source("alos-fnf")
        acc.add_api_call("worldcover")
        acc.add_api_call("wdpa")
        acc.add_api_call("lulc")
        acc.add_api_call("alos")
        landsat_baseline = results.get("landsat_baseline", {})
        if landsat_baseline.get("available"):
            acc.add_source("landsat-c2-l2")
            acc.increment("landsat_scenes_sampled", len(landsat_baseline.get("scenes", [])))
        acc.record_phase_duration("eudr_datasets", time.monotonic() - t0)


def _run_landsat_baseline(
    flat_bbox: list[float],
    results: dict[str, Any],
) -> None:
    """Phase 1e: Landsat C2 L2 historical NDVI baseline (#609).

    Samples 2 dry-season windows (2013-2014, 2015-2016) to establish
    a pre-Sentinel-2 forest baseline for EUDR evidence.
    """
    from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

    log_phase("enrichment", "landsat_baseline_start")
    windows = [
        ("2013-06-01", "2014-09-30"),
        ("2015-06-01", "2016-09-30"),
    ]
    baseline_results: list[dict[str, Any]] = []
    for start, end in windows:
        result = compute_landsat_ndvi(flat_bbox, start, end)
        if result is not None:
            result.pop("geotiff_bytes", None)  # don't store raster in manifest
            baseline_results.append(result)

    results["landsat_baseline"] = {
        "available": len(baseline_results) > 0,
        "scenes": baseline_results,
        "source": "landsat-c2-l2",
    }
    log_phase(
        "enrichment",
        "landsat_baseline_done",
        scenes=len(baseline_results),
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
    acc: ResourceAccumulator | None = None,
) -> tuple[list[dict[str, Any] | None], list[str | None]]:
    """Phase 2/3: mosaic registration + NDVI computation (COG or tile fallback)."""
    t0 = time.monotonic()
    # 2. Mosaic registration (parallel — each frame is independent)
    log_phase("enrichment", "mosaic_start", frames=len(frame_plan))
    search_ids: list[str | None] = [None] * len(frame_plan)
    ndvi_search_ids: list[str | None] = [None] * len(frame_plan)
    display_collections: list[str] = [str(f.get("collection", "")) for f in frame_plan]

    def _register_one(idx: int, f: dict[str, Any]) -> tuple[int, str | None, str | None, str]:
        cloud_collections = {"sentinel-2-l2a", "landsat-c2-l2"}
        extra: list[dict[str, Any]] = (
            [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}]
            if f["collection"] in cloud_collections
            else []
        )
        with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS, trust_env=False) as cl:
            sid = None
            display_collection = str(f.get("collection", ""))
            if f.get("rgb_display_suitable", True):
                sid = register_mosaic(f["collection"], f["start"], f["end"], bbox, extra, cl)

            # If NAIP is preferred but unavailable for this frame/year, fall
            # back to Sentinel-2 RGB so the viewer still gets the best
            # available visual source instead of a missing/blank RGB layer.
            if f["is_naip"] and sid is None and f.get("rgb_display_suitable", True):
                sid = register_mosaic(
                    "sentinel-2-l2a",
                    f["start"],
                    f["end"],
                    bbox,
                    [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}],
                    cl,
                )
                if sid:
                    display_collection = "sentinel-2-l2a"

            nsid = sid
            # When the RGB mosaic was skipped (unsuitable) or failed, register a
            # Sentinel-2 mosaic for NDVI so the viewer has a vegetation tile to show.
            # This covers sentinel-2-l2a (direct) and landsat-c2-l2 (cross-sensor) —
            # previously Landsat frames were left with nsid=None here.
            if sid is None and f["collection"] in {"sentinel-2-l2a", "landsat-c2-l2"}:
                nsid = register_mosaic(
                    "sentinel-2-l2a",
                    f["start"],
                    f["end"],
                    bbox,
                    [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}],
                    cl,
                )
            if f["is_naip"]:
                if display_collection == "sentinel-2-l2a" and sid is not None:
                    nsid = sid
                else:
                    nsid = register_mosaic(
                        "sentinel-2-l2a",
                        f["start"],
                        f["end"],
                        bbox,
                        [{"op": "<=", "args": [{"property": "eo:cloud_cover"}, 20]}],
                        cl,
                    )
        return idx, sid, nsid, display_collection

    with ThreadPoolExecutor(max_workers=DEFAULT_ENRICHMENT_CONCURRENCY) as pool:
        futures = [pool.submit(_register_one, i, f) for i, f in enumerate(frame_plan)]
        for fut in as_completed(futures):
            try:
                idx, sid, nsid, display_collection = fut.result()
            except Exception:
                logger.warning("mosaic registration failed for one frame", exc_info=True)
                continue
            search_ids[idx] = sid
            ndvi_search_ids[idx] = nsid
            display_collections[idx] = display_collection

    results["search_ids"] = search_ids
    results["ndvi_search_ids"] = ndvi_search_ids
    results["display_collections"] = display_collections
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
        cog_result = None
        if f["collection"] == "landsat-c2-l2":
            cog_result = compute_landsat_ndvi(flat_bbox, f["start"], f["end"])
        elif f["collection"] == "sentinel-2-l2a" or f["is_naip"]:
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
            with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS, trust_env=False) as cl:
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
        f["display_collection"] = display_collections[i]
        season_key = f["season"]
        year = f["year"]
        if f["display_collection"] == "naip":
            f["label"] = f"NAIP Summer {year}"
        elif f["display_collection"] == "landsat-c2-l2":
            f["label"] = f"Landsat {season_key.capitalize()} {year}"
        else:
            f["label"] = f"{season_key.capitalize()} {year}"
        if f["display_collection"] == "naip":
            res = "0.6" if year > 2014 else "1.0"
            src = "NAIP © USDA"
        elif f["display_collection"] == "landsat-c2-l2":
            res = "30"
            src = "Landsat C2 L2"
        else:
            res = "10"
            src = "Sentinel-2 L2A"
        f["info"] = f"{src} | {res} m/px | {f['start']} → {f['end']}"
        ndvi_stat = ndvi_stats[i] if i < len(ndvi_stats) else None
        f["provenance"] = {
            "collection": f.get("display_collection") or f.get("collection", ""),
            "requested_collection": f.get("collection", ""),
            "display_search_id": search_ids[i],
            "ndvi_search_id": ndvi_search_ids[i],
            "ndvi_scene_id": ndvi_stat.get("scene_id") if ndvi_stat else None,
            "resolution_m": f.get("display_resolution_m")
            or COLLECTION_DISPLAY_GSD_M.get(str(f.get("collection", ""))),
            "cloud_cover_pct": ndvi_stat.get("cloud_cover") if ndvi_stat else None,
            "acquired_at": ndvi_stat.get("datetime") if ndvi_stat else None,
            "artifact_path": f.get("ndvi_raster_path"),
            "label": f.get("label", ""),
        }

    if acc:
        mosaic_count = sum(1 for s in search_ids if s)
        acc.increment("mosaic_registrations", mosaic_count)
        acc.increment("ndvi_computations", ndvi_count)
        s2_count = sum(
            1 for f in frame_plan if f["collection"] == "sentinel-2-l2a" and f.get("search_id")
        )
        if s2_count:
            acc.add_source("sentinel-2-l2a")
            acc.increment("sentinel2_scenes_registered", s2_count)
        # PC API calls: 1 per mosaic registration + 1 per NDVI computation
        acc.add_api_call("planetary_computer", count=mosaic_count + ndvi_count)
        acc.record_phase_duration("mosaic_ndvi", time.monotonic() - t0)

    return ndvi_stats, ndvi_raster_paths


def _run_change_detection_phase(
    frame_plan: list[dict[str, Any]],
    ndvi_raster_paths: list[str | None],
    output_container: str,
    project_name: str,
    timestamp: str,
    storage: BlobStorageClient,
    results: dict[str, Any],
    acc: ResourceAccumulator | None = None,
) -> None:
    """Phase 5: compare same-season NDVI rasters year-over-year."""
    t0 = time.monotonic()
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
        comparisons = change_results["summary"]["comparisons"]
        log_phase(
            "enrichment",
            "change_detection_done",
            comparisons=comparisons,
            trajectory=change_results["summary"].get("trajectory"),
        )
        if acc:
            acc.increment("change_detection_comparisons", comparisons)
    else:
        results["change_detection"] = {"season_changes": [], "summary": {}}

    if acc:
        acc.record_phase_duration("change_detection", time.monotonic() - t0)


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

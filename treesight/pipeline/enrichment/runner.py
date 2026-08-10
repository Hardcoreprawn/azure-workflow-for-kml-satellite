"""Enrichment orchestrator — runs weather, flood, fire, mosaic, NDVI, and stores manifest."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from typing import Any

from treesight.constants import (
    DEFAULT_ENRICHMENT_CONCURRENCY,
    EUDR_CUTOFF_DATE,
    MULTI_REGION_THRESHOLD_KM,
)
from treesight.geo import centroid as _geo_centroid
from treesight.geo import haversine_km as _geo_haversine_km
from treesight.log import log_phase
from treesight.pipeline.enrichment._phase_runners import (
    _run_aoi_metrics_phase,
    _run_change_detection_phase,
    _run_eudr_phase,
    _run_flood_fire_phase,
    _run_mosaic_ndvi_phase,
    _run_weather_phase,
)
from treesight.pipeline.enrichment.frames import build_frame_plan
from treesight.pipeline.enrichment.mosaic import _coords_to_bbox
from treesight.pipeline.enrichment.resource_accumulator import ResourceAccumulator
from treesight.storage.client import BlobStorageClient

logger = logging.getLogger(__name__)


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
    aoi_acc = ResourceAccumulator()
    _run_weather_phase(center_lat, center_lon, first_date, last_date, result, acc=aoi_acc)
    _run_flood_fire_phase(bbox, center_lat, center_lon, result, acc=aoi_acc)

    if eudr_mode:
        _run_eudr_phase(bbox, center_lat, center_lon, result, acc=aoi_acc)

    _ndvi_stats, ndvi_raster_paths = _run_mosaic_ndvi_phase(
        bbox,
        coords,
        frame_plan,
        project_name,
        timestamp,
        output_container,
        storage,
        result,
        acc=aoi_acc,
    )

    _run_change_detection_phase(
        frame_plan,
        ndvi_raster_paths,
        output_container,
        project_name,
        timestamp,
        storage,
        result,
        acc=aoi_acc,
    )

    # Deforestation-free determination (#603)
    if eudr_mode:
        from treesight.pipeline.enrichment.determination import (
            determine_deforestation_free,
        )

        result["determination"] = determine_deforestation_free(result)

    result["resource_usage"] = aoi_acc.to_dict()
    return result


# ── Multi-region detection ─────────────────────────────────────────────────


def _is_multi_region(per_aoi_coords: list[dict]) -> bool:
    """Return True when any two AOI centroids are farther apart than MULTI_REGION_THRESHOLD_KM.

    When True, union-level mosaic/NDVI/change-detection and EUDR stats would
    span continents and are geographically meaningless.  Each AOI's data is
    still produced via the per-AOI fan-out.
    """
    if len(per_aoi_coords) < 2:
        return False

    centroids = []
    for entry in per_aoi_coords:
        coords = entry.get("coords")
        if coords:
            centroids.append(_geo_centroid(coords))

    for i in range(len(centroids)):
        for j in range(i + 1, len(centroids)):
            lon1, lat1 = centroids[i]
            lon2, lat2 = centroids[j]
            if _geo_haversine_km(lon1, lat1, lon2, lat2) > MULTI_REGION_THRESHOLD_KM:
                return True
    return False


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
    acc = ResourceAccumulator()
    _run_weather_phase(center_lat, center_lon, first_date, last_date, results, acc=acc)

    # 1b/1c. Flood + fire
    _run_flood_fire_phase(bbox, center_lat, center_lon, results, acc=acc)

    # Detect multi-region: AOI centroids spanning > MULTI_REGION_THRESHOLD_KM mean
    # union-level imagery and EUDR stats are geographically meaningless (#860).
    multi_region = _is_multi_region(per_aoi_coords) if per_aoi_coords else False
    if multi_region:
        results["multi_region"] = True
        log_phase("enrichment", "multi_region_detected", aoi_count=len(per_aoi_coords or []))

    # 1d. EUDR-specific enrichments (WorldCover + WDPA) — skipped for multi-region
    if eudr_mode and not multi_region:
        _run_eudr_phase(bbox, center_lat, center_lon, results, acc=acc)

    # 2/3. Mosaic registration + NDVI computation — skipped for multi-region
    if not multi_region:
        ndvi_stats, ndvi_raster_paths = _run_mosaic_ndvi_phase(
            bbox,
            coords,
            frame_plan,
            project_name,
            timestamp,
            output_container,
            storage,
            results,
            acc=acc,
        )
    else:
        ndvi_stats, ndvi_raster_paths = [], []

    # 5. Change detection — skipped for multi-region
    if not multi_region:
        _run_change_detection_phase(
            frame_plan,
            ndvi_raster_paths,
            output_container,
            project_name,
            timestamp,
            storage,
            results,
            acc=acc,
        )

    # 6. Per-AOI quantitative metrics
    if aoi_list is not None:
        _run_aoi_metrics_phase(aoi_list, ndvi_stats, results)

    # 6b. Per-AOI enrichment — parallel fan-out; each AOI gets weather, NDVI, change detection
    if per_aoi_coords and len(per_aoi_coords) > 1:
        log_phase("enrichment", "per_aoi_start", aoi_count=len(per_aoi_coords))
        per_aoi_enrichment: list[dict[str, Any]] = [{}] * len(per_aoi_coords)

        def _enrich_safe(entry: dict[str, Any]) -> dict[str, Any]:
            try:
                return _enrich_single_aoi(
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
            except Exception:
                logger.warning(
                    "Per-AOI enrichment failed for %s — skipping",
                    entry.get("name", "?"),
                    exc_info=True,
                )
                return {"name": entry.get("name", ""), "error": "enrichment_failed"}

        # Bound max_workers: never exceed the cap, never create more workers than AOIs,
        # never allow 0 (which raises ValueError). Nested calls to _run_mosaic_ndvi_phase
        # may themselves use thread pools, so we also clamp to avoid runaway concurrency.
        max_workers = max(1, min(DEFAULT_ENRICHMENT_CONCURRENCY, len(per_aoi_coords)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {
                pool.submit(_enrich_safe, entry): idx for idx, entry in enumerate(per_aoi_coords)
            }
            for future in as_completed(future_to_idx):
                per_aoi_enrichment[future_to_idx[future]] = future.result()

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

    # Merge per-AOI resource usage into the top-level accumulator
    per_aoi_enrichment = results.get("per_aoi_enrichment", [])
    succeeded_aois = [r for r in per_aoi_enrichment if "error" not in r]
    acc.increment("per_aoi_enrichments", len(succeeded_aois))
    for aoi_r in succeeded_aois:
        usage = aoi_r.get("resource_usage")
        if isinstance(usage, dict):
            acc.merge(ResourceAccumulator.from_dict(usage))
    results["resource_usage"] = acc.to_dict()
    results["estimated_cost_pence"] = acc.estimate_cost_pence()

    results["enriched_at"] = datetime.now(UTC).isoformat()
    if eudr_mode:
        results["eudr_mode"] = True
        results["eudr_date_start"] = date_start

        # Overall deforestation-free determination (#603).
        # Skipped for multi-region runs: union-level change_detection is absent,
        # so a top-level determination would be misleading.  Per-AOI determinations
        # are available in per_aoi_enrichment instead.
        if not multi_region:
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


# ── Sub-step functions for DF activity splitting (#574) ───────


def enrich_data_sources(
    coords: list[list[float]],
    *,
    eudr_mode: bool = False,
    date_start: str | None = None,
    date_end: str | None = None,
    cadence: str = "maximum",
    max_history_years: int | None = None,
) -> dict[str, Any]:
    """Sub-step 1: weather, flood/fire, EUDR datasets.

    Returns a partial results dict that subsequent sub-steps extend.
    Runs independently from ``enrich_imagery`` — these two fan-out in parallel.
    """
    bbox = _coords_to_bbox(coords)

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
        logger.warning("No frames matched date filters — returning partial results")
        results["enriched_at"] = datetime.now(UTC).isoformat()
        if eudr_mode:
            results["eudr_mode"] = True
            results["eudr_date_start"] = date_start
        return results

    first_date = frame_plan[0]["start"]
    last_date = frame_plan[-1]["end"]
    acc = ResourceAccumulator()
    _run_weather_phase(center_lat, center_lon, first_date, last_date, results, acc=acc)
    _run_flood_fire_phase(bbox, center_lat, center_lon, results, acc=acc)

    if eudr_mode:
        _run_eudr_phase(bbox, center_lat, center_lon, results, acc=acc)
        results["eudr_mode"] = True
        results["eudr_date_start"] = date_start

    results["resource_usage"] = acc.to_dict()
    return results


def enrich_imagery(
    coords: list[list[float]],
    *,
    eudr_mode: bool = False,
    date_start: str | None = None,
    date_end: str | None = None,
    cadence: str = "maximum",
    max_history_years: int | None = None,
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
) -> dict[str, Any]:
    """Sub-step 2: mosaic registration, NDVI computation, change detection.

    Runs independently from ``enrich_data_sources`` — these two fan-out in parallel.
    Returns a partial results dict with imagery-specific keys.
    """
    bbox = _coords_to_bbox(coords)

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

    results: dict[str, Any] = {"frame_plan": frame_plan}
    if not frame_plan:
        return {}

    acc = ResourceAccumulator()
    _ndvi_stats, ndvi_raster_paths = _run_mosaic_ndvi_phase(
        bbox,
        coords,
        frame_plan,
        project_name,
        timestamp,
        output_container,
        storage,
        results,
        acc=acc,
    )

    _run_change_detection_phase(
        frame_plan,
        ndvi_raster_paths,
        output_container,
        project_name,
        timestamp,
        storage,
        results,
        acc=acc,
    )

    results["resource_usage"] = acc.to_dict()
    return results


def enrich_single_aoi_step(
    aoi_entry: dict[str, Any],
    *,
    date_start: str | None = None,
    date_end: str | None = None,
    cadence: str = "maximum",
    max_history_years: int | None = None,
    eudr_mode: bool = False,
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
) -> dict[str, Any]:
    """Sub-step 3a: per-AOI enrichment — one call per AOI, fan-out via task_all.

    Thin wrapper around ``_enrich_single_aoi`` with error containment so
    a single AOI failure doesn't poison the whole batch.
    """
    try:
        return _enrich_single_aoi(
            aoi_entry,
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
    except Exception:
        logger.warning(
            "Per-AOI enrichment failed for %s — returning error stub",
            aoi_entry.get("name", "?"),
            exc_info=True,
        )
        return {"name": aoi_entry.get("name", ""), "error": "enrichment_failed"}


def enrich_finalize(
    data_sources: dict[str, Any],
    imagery: dict[str, Any],
    per_aoi_results: list[dict[str, Any]],
    *,
    eudr_mode: bool = False,
    date_start: str | None = None,
    project_name: str,
    timestamp: str,
    output_container: str,
    storage: BlobStorageClient,
) -> dict[str, Any]:
    """Sub-step 4: merge parallel results, apply determination, store manifest.

    Merges ``data_sources`` (weather/flood/EUDR) and ``imagery``
    (mosaics/NDVI/change-detection), appends per-AOI enrichment, writes
    the final manifest to blob storage.
    """
    # Merge: data_sources is the base, imagery overlays
    ds_usage = data_sources.get("resource_usage")
    img_usage = imagery.get("resource_usage")
    merged = {**data_sources, **imagery}
    merged.pop("resource_usage", None)

    # Combine resource accumulators from parallel fan-out
    acc = ResourceAccumulator()
    if ds_usage:
        acc.merge(ResourceAccumulator.from_dict(ds_usage))
    if img_usage:
        acc.merge(ResourceAccumulator.from_dict(img_usage))

    if per_aoi_results:
        merged["per_aoi_enrichment"] = per_aoi_results
        succeeded = [r for r in per_aoi_results if "error" not in r]
        acc.increment("per_aoi_enrichments", len(succeeded))
        log_phase(
            "enrichment",
            "per_aoi_done",
            total=len(per_aoi_results),
            succeeded=len(succeeded),
        )

    merged["resource_usage"] = acc.to_dict()
    merged["estimated_cost_pence"] = acc.estimate_cost_pence()
    merged["enriched_at"] = datetime.now(UTC).isoformat()
    if eudr_mode:
        merged["eudr_mode"] = True
        merged["eudr_date_start"] = date_start
        from treesight.pipeline.enrichment.determination import (
            determine_deforestation_free,
        )

        merged["determination"] = determine_deforestation_free(merged)

    manifest_path = f"enrichment/{project_name}/{timestamp}/timelapse_payload.json"
    storage.upload_json(output_container, manifest_path, merged)
    merged["manifest_path"] = manifest_path

    log_phase("enrichment", "finalize_done", manifest=manifest_path)
    return merged

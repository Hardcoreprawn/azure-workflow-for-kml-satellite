"""Enrichment orchestrator — runs weather, mosaic, NDVI, and stores manifest."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from treesight.log import log_phase
from treesight.pipeline.enrichment.frames import build_frame_plan
from treesight.pipeline.enrichment.mosaic import _coords_to_bbox, register_mosaic
from treesight.pipeline.enrichment.ndvi import fetch_ndvi_stat
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
) -> dict[str, Any]:
    """Run full enrichment pipeline — the main entry point.

    Fetches weather, registers mosaics, samples NDVI, and stores everything
    in blob storage as a single timelapse_payload.json manifest.
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

    # 3. NDVI sampling (batches of 4)
    log_phase("enrichment", "ndvi_start", frames=len(frame_plan))
    ndvi_stats: list[dict[str, float] | None] = []
    for _i, nsid in enumerate(ndvi_search_ids):
        if nsid:
            stat = fetch_ndvi_stat(nsid, coords, http_client)
            ndvi_stats.append(stat)
        else:
            ndvi_stats.append(None)

    results["ndvi_stats"] = ndvi_stats
    ndvi_count = sum(1 for s in ndvi_stats if s)
    log_phase("enrichment", "ndvi_done", sampled=ndvi_count, total=len(ndvi_stats))

    # 4. Build labelled frame metadata (mirrors frontend framesMeta)
    for i, f in enumerate(frame_plan):
        f["search_id"] = search_ids[i]
        f["ndvi_search_id"] = ndvi_search_ids[i]
        f["ndvi_stat"] = ndvi_stats[i]
        season_key = f["season"]
        year = f["year"]
        if f["is_naip"]:
            f["label"] = f"NAIP Summer {year}"
        else:
            f["label"] = f"{season_key.capitalize()} {year}"
        res = "0.6" if f["is_naip"] and year > 2014 else "1.0" if f["is_naip"] else "10"
        src = "NAIP © USDA" if f["is_naip"] else "Sentinel-2 L2A"
        f["info"] = f"{src} | {res} m/px | {f['start']} → {f['end']}"

    # 5. Store manifest
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

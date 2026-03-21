"""Phase 4 — Enrichment: weather, NDVI, mosaic registration, and analysis (§3.4).

Downloads and persists all external data the frontend needs so the viewer
serves pipeline-produced artifacts instead of fetching directly from
third-party APIs.  This makes every timelapse fully reproducible and
auditable.
"""

from __future__ import annotations

import logging
import math
import struct
import time
import zlib
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS
from treesight.log import log_phase
from treesight.storage.client import BlobStorageClient

logger = logging.getLogger(__name__)

PC_API = "https://planetarycomputer.microsoft.com/api/data/v1"
OPEN_METEO_API = "https://archive-api.open-meteo.com/v1/archive"

# Seasonal definitions matching the frontend
SEASONS: list[dict[str, Any]] = [
    {"key": "winter", "label": "Winter", "months": [12, 1, 2]},
    {"key": "spring", "label": "Spring", "months": [3, 4, 5]},
    {"key": "summer", "label": "Summer", "months": [6, 7, 8]},
    {"key": "autumn", "label": "Autumn", "months": [9, 10, 11]},
]
SEASONAL_YEARS = list(range(2018, 2026))
NAIP_ONLY_YEARS = [2012, 2014, 2016]
NAIP_SUMMERS = {
    "2012-summer",
    "2014-summer",
    "2016-summer",
    "2018-summer",
    "2020-summer",
    "2022-summer",
}


def _aoi_has_naip(coords: list[list[float]]) -> bool:
    """Check if all coords fall within CONUS (NAIP coverage).

    Coordinates are ``[lon, lat]`` pairs per project convention
    (see :pymod:`treesight.constants`).
    """
    for c in coords:
        lon, lat = c[0], c[1]
        if lat < 24 or lat > 50 or lon < -125 or lon > -66:
            return False
    return True


def _season_window(year: int, season: dict[str, Any]) -> dict[str, str]:
    """Compute date window for a season/year, matching frontend logic."""
    if season["key"] == "winter":
        return {"start": f"{year - 1}-12-01", "end": f"{year}-02-28"}
    m0 = season["months"][0]
    m2 = season["months"][2]
    start = f"{year}-{m0:02d}-01"
    # Last day of end month
    if m2 == 2:
        end_day = 28
    elif m2 in (4, 6, 9, 11):
        end_day = 30
    else:
        end_day = 31
    end = f"{year}-{m2:02d}-{end_day}"
    return {"start": start, "end": end}


def _coords_to_bbox(
    coords: list[list[float]],
    pad: float = 0.02,
) -> list[list[float]]:
    """Compute a bounding box polygon from AOI coords.

    Coordinates are ``[lon, lat]`` pairs.
    """
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lat = min(lats) - pad
    max_lat = max(lats) + pad
    min_lon = min(lons) - pad
    max_lon = max(lons) + pad
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def build_frame_plan(coords: list[list[float]]) -> list[dict[str, Any]]:
    """Build the ordered frame list — mirrors frontend buildFramePlan()."""
    frames: list[dict[str, Any]] = []
    has_naip = _aoi_has_naip(coords)
    summer = SEASONS[2]

    if has_naip:
        for yr in NAIP_ONLY_YEARS:
            w = _season_window(yr, summer)
            frames.append(
                {
                    "year": yr,
                    "season": "summer",
                    "start": w["start"],
                    "end": w["end"],
                    "collection": "naip",
                    "asset": "image",
                    "is_naip": True,
                }
            )

    for yr in SEASONAL_YEARS:
        for s in SEASONS:
            w = _season_window(yr, s)
            naip_key = f"{yr}-{s['key']}"
            use_naip = has_naip and naip_key in NAIP_SUMMERS
            frames.append(
                {
                    "year": yr,
                    "season": s["key"],
                    "start": w["start"],
                    "end": w["end"],
                    "collection": "naip" if use_naip else "sentinel-2-l2a",
                    "asset": "image" if use_naip else "visual",
                    "is_naip": use_naip,
                }
            )

    return frames


def register_mosaic(
    collection: str,
    date_start: str,
    date_end: str,
    bbox: list[list[float]],
    extra_filters: list[dict[str, Any]] | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """Register a Planetary Computer mosaic and return the search ID."""
    filter_args: list[dict[str, Any]] = [
        {
            "op": "t_intersects",
            "args": [{"property": "datetime"}, {"interval": [date_start, date_end]}],
        },
        {
            "op": "s_intersects",
            "args": [
                {"property": "geometry"},
                {"type": "Polygon", "coordinates": [bbox]},
            ],
        },
    ]
    if extra_filters:
        filter_args.extend(extra_filters)

    sortby = (
        [{"field": "datetime", "direction": "desc"}]
        if collection == "naip"
        else [{"field": "eo:cloud_cover", "direction": "asc"}]
    )

    body: dict[str, Any] = {
        "collections": [collection],
        "filter-lang": "cql2-json",
        "filter": {"op": "and", "args": filter_args},
        "sortby": sortby,
    }

    http = client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    try:
        r = http.post(f"{PC_API}/mosaic/register", json=body)
        r.raise_for_status()
        return r.json().get("searchid")
    except Exception as exc:
        logger.warning("Mosaic registration failed for %s: %s", collection, exc)
        return None


def fetch_weather(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    """Fetch historical weather from Open-Meteo and return structured data."""
    url = (
        f"{OPEN_METEO_API}"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=temperature_2m_mean,precipitation_sum"
        f"&timezone=auto"
    )
    try:
        r = httpx.get(url, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        r.raise_for_status()
        d = r.json()
        daily = d.get("daily", {})
        return {
            "dates": daily.get("time", []),
            "temp": daily.get("temperature_2m_mean", []),
            "precip": daily.get("precipitation_sum", []),
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return None


def aggregate_weather_monthly(weather: dict[str, Any]) -> dict[str, Any]:
    """Aggregate daily weather into monthly averages (mirrors frontend)."""
    dates = weather.get("dates", [])
    temps = weather.get("temp", [])
    precips = weather.get("precip", [])

    months: dict[str, dict[str, Any]] = {}
    for i, date in enumerate(dates):
        key = date[:7]  # YYYY-MM
        if key not in months:
            months[key] = {"temp": [], "precip": 0.0}
        if i < len(temps) and temps[i] is not None:
            months[key]["temp"].append(temps[i])
        if i < len(precips) and precips[i] is not None:
            months[key]["precip"] += precips[i]

    keys = sorted(months.keys())
    return {
        "labels": keys,
        "temp": [
            round(sum(months[k]["temp"]) / len(months[k]["temp"]), 1) if months[k]["temp"] else None
            for k in keys
        ],
        "precip": [round(months[k]["precip"], 1) for k in keys],
    }


def fetch_ndvi_stat(
    search_id: str,
    coords: list[list[float]],
    client: httpx.Client | None = None,
) -> dict[str, float] | None:
    """Sample NDVI from a single PC tile at z12 — mirrors frontend logic.

    Uses the PC statistics endpoint instead of pixel-level tile parsing,
    which avoids needing Pillow/PIL.
    """
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    lat = (min(lats) + max(lats)) / 2
    lon = (min(lons) + max(lons)) / 2

    z = 12
    n = 2**z
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)

    # Use the tile info endpoint to get statistics without downloading pixels
    url = (
        f"{PC_API}/mosaic/tiles/{search_id}"
        f"/WebMercatorQuad/{z}/{x}/{y}@1x"
        f"?collection=sentinel-2-l2a&assets=B08&assets=B04"
        f"&expression=(B08_b1-B04_b1)/(B08_b1%2BB04_b1)"
        f"&rescale=-0.2,0.8&nodata=0&format=png"
    )
    http = client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    try:
        r = http.get(url)
        if r.status_code != 200:
            return None

        # Parse PNG pixel data directly using struct/zlib (no PIL needed)
        png_data = r.content
        ndvi_values = _extract_red_channel_from_png(png_data)
        if not ndvi_values:
            return None

        # Map red channel (0-255) back to NDVI range (-0.2 to 0.8)
        mapped = [-0.2 + (v / 255) * 1.0 for v in ndvi_values]
        mean_v = sum(mapped) / len(mapped)
        return {
            "mean": round(mean_v, 3),
            "min": round(min(mapped), 3),
            "max": round(max(mapped), 3),
        }
    except Exception as exc:
        logger.warning("NDVI stat fetch failed for %s: %s", search_id, exc)
        return None


def _extract_red_channel_from_png(png_bytes: bytes) -> list[int]:
    """Extract non-transparent red channel values from a PNG without PIL.

    Handles RGBA 8-bit PNGs (the format PC returns for expression tiles).
    """
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return []

    # Parse IHDR
    pos = 8
    width = height = bit_depth = color_type = 0
    raw_idat = b""

    while pos < len(png_bytes):
        chunk_len = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        chunk_type = png_bytes[pos + 4 : pos + 8]
        chunk_data = png_bytes[pos + 8 : pos + 8 + chunk_len]

        if chunk_type == b"IHDR":
            width = struct.unpack(">I", chunk_data[0:4])[0]
            height = struct.unpack(">I", chunk_data[4:8])[0]
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
        elif chunk_type == b"IDAT":
            raw_idat += chunk_data
        elif chunk_type == b"IEND":
            break

        pos += 12 + chunk_len  # 4 len + 4 type + data + 4 crc

    if not width or not height or bit_depth != 8:
        return []

    # Determine bytes per pixel
    if color_type == 6:  # RGBA
        bpp = 4
    elif color_type == 2:  # RGB
        bpp = 3
    else:
        return []  # unsupported

    try:
        decompressed: bytes = zlib.decompress(raw_idat)
    except zlib.error:
        return []

    # Undo PNG filtering (simplified — handles filter type 0 and 1)
    stride = 1 + width * bpp
    if len(decompressed) < stride * height:
        return []

    red_values: list[int] = []
    prev_row = bytearray(width * bpp)

    for row in range(height):
        row_start = row * stride
        filter_type = cast(int, decompressed[row_start])
        raw = bytearray(decompressed[row_start + 1 : row_start + stride])

        if filter_type == 1:  # Sub
            for i in range(bpp, len(raw)):
                raw[i] = (raw[i] + raw[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(len(raw)):
                raw[i] = (raw[i] + prev_row[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(len(raw)):
                left = raw[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                raw[i] = (raw[i] + (left + up) // 2) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(len(raw)):
                left = raw[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                raw[i] = (raw[i] + _paeth_predictor(left, up, up_left)) & 0xFF

        # Extract red channel for non-transparent pixels
        for px in range(width):
            offset = px * bpp
            r_val = raw[offset]
            alpha = raw[offset + 3] if bpp == 4 else 255
            if alpha > 0:
                red_values.append(r_val)

        prev_row = raw

    return red_values


def _paeth_predictor(a: int, b: int, c: int) -> int:
    """PNG Paeth predictor filter."""
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    return c


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

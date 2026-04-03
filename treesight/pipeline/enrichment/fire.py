"""Fire hotspot detection — NASA FIRMS VIIRS integration.

Fetches active fire/hotspot data from NASA's Fire Information for
Resource Management System (FIRMS) for an AOI bounding box.
Requires a free FIRMS MAP_KEY (env var FIRMS_API_KEY).
"""

from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

FIRMS_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
# NOTE: read at import time; changes to env vars after import are not picked up.
FIRMS_API_KEY = os.environ.get("FIRMS_API_KEY", "")

# Default source and day range
FIRMS_SOURCE = "VIIRS_SNPP_NRT"
FIRMS_DAY_RANGE = 10  # 1-10 days


def fetch_fire_hotspots(
    bbox: list[list[float]],
    *,
    day_range: int = FIRMS_DAY_RANGE,
) -> dict[str, Any]:
    """Fetch recent fire hotspots from NASA FIRMS for the AOI.

    Parameters
    ----------
    bbox : list of [lon, lat] pairs
        AOI bounding box corners.
    day_range : int
        Number of recent days to query (1-10).

    Returns
    -------
    dict with "source", "events" list, and "count".
    """
    if not FIRMS_API_KEY:
        logger.info("FIRMS_API_KEY not set — fire hotspot detection disabled")
        return {"source": "firms_disabled", "events": [], "count": 0}

    lons = [p[0] for p in bbox]
    lats = [p[1] for p in bbox]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    # FIRMS area endpoint: /api/area/csv/{key}/{source}/{bbox}/{day_range}
    day_range = max(1, min(10, day_range))  # Clamp to FIRMS 1-10 range
    bbox_str = f"{min_lon},{min_lat},{max_lon},{max_lat}"
    url = f"{FIRMS_API_BASE}/{FIRMS_API_KEY}/{FIRMS_SOURCE}/{bbox_str}/{day_range}"

    try:
        resp = httpx.get(url, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        events = _parse_firms_csv(resp.text)
        return {"source": "firms_viirs", "events": events, "count": len(events)}
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "FIRMS fire hotspot fetch failed: HTTP %s",
            exc.response.status_code,
        )
        return {"source": "firms_error", "events": [], "count": 0}
    except Exception as exc:
        logger.warning(
            "FIRMS fire hotspot fetch failed: %s",
            type(exc).__name__,
        )
        return {"source": "firms_error", "events": [], "count": 0}


def _parse_firms_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse FIRMS CSV response into a list of fire event dicts."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    events: list[dict[str, Any]] = []

    for i, row in enumerate(reader):
        if i >= 100:  # Limit to 100 events
            break
        # Require latitude/longitude; skip rows where they are missing or blank
        lat_str = (row.get("latitude") or "").strip()
        lon_str = (row.get("longitude") or "").strip()
        if not lat_str or not lon_str:
            continue
        try:
            events.append(
                {
                    "source": "firms",
                    "latitude": float(lat_str),
                    "longitude": float(lon_str),
                    "acq_date": row.get("acq_date", ""),
                    "acq_time": row.get("acq_time", ""),
                    "confidence": row.get("confidence", ""),
                    "frp": float(row["frp"]) if row.get("frp") else None,
                    "bright_ti4": float(row["bright_ti4"]) if row.get("bright_ti4") else None,
                }
            )
        except (ValueError, KeyError):
            continue

    return events

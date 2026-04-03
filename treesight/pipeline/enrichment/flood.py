"""Flood event detection — UK EA + US USGS integration.

Fetches recent flood warnings and streamflow data for the AOI bounding box.
Routes by centroid geolocation: UK → EA Flood Monitoring, US → USGS NWIS.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# UK Environment Agency Flood Monitoring
EA_FLOOD_API = "https://environment.data.gov.uk/flood-monitoring/id/floods"

# US Geological Survey National Water Information System
USGS_NWIS_API = "https://waterservices.usgs.gov/nwis/iv/"


def _is_uk(lat: float, lon: float) -> bool:
    """Rough check if centroid falls within UK bounding box."""
    return 49.0 <= lat <= 61.0 and -8.0 <= lon <= 2.0


def _is_us(lat: float, lon: float) -> bool:
    """Rough check if centroid falls within contiguous US bounding box."""
    return 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0


def fetch_ea_floods(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> list[dict[str, Any]]:
    """Fetch active flood warnings from UK EA within a bounding box.

    The EA API supports lat/long filtering.  Returns a list of flood
    event dicts with severity, description, and area info.
    """
    params = {
        "min-lat": str(min_lat),
        "min-long": str(min_lon),
        "max-lat": str(max_lat),
        "max-long": str(max_lon),
        "_limit": "50",
    }
    try:
        resp = httpx.get(EA_FLOOD_API, params=params, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        events: list[dict[str, Any]] = []
        for item in items:
            events.append(
                {
                    "source": "ea",
                    "severity": item.get("severityLevel", ""),
                    "description": item.get("description", ""),
                    "area": item.get("eaAreaName", ""),
                    "message": item.get("message", ""),
                    "time_raised": item.get("timeRaised", ""),
                    "time_changed": item.get("timeSeverityChanged", ""),
                }
            )
        return events
    except Exception as exc:
        logger.warning("EA flood fetch failed: %s", exc)
        return []


def fetch_usgs_streamflow(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
) -> list[dict[str, Any]]:
    """Fetch latest streamflow readings from USGS NWIS within a bounding box.

    Uses instantaneous values service with geographic bounding box filter.
    Returns stream gauge readings that may indicate flooding.
    """
    params = {
        "format": "json",
        "bBox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "parameterCd": "00060",  # Discharge, cubic feet per second
        "siteStatus": "active",
        "period": "P7D",  # Last 7 days
    }
    try:
        resp = httpx.get(USGS_NWIS_API, params=params, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        ts_list = data.get("value", {}).get("timeSeries", [])
        events: list[dict[str, Any]] = []
        for ts in ts_list[:20]:  # Limit to 20 gauges
            site_info = ts.get("sourceInfo", {})
            values = ts.get("values", [{}])
            latest_values = values[0].get("value", []) if values else []
            latest = latest_values[-1] if latest_values else {}
            events.append(
                {
                    "source": "usgs",
                    "site_name": site_info.get("siteName", ""),
                    "site_code": site_info.get("siteCode", [{}])[0].get("value", ""),
                    "latitude": site_info.get("geoLocation", {})
                    .get("geogLocation", {})
                    .get("latitude"),
                    "longitude": site_info.get("geoLocation", {})
                    .get("geogLocation", {})
                    .get("longitude"),
                    "discharge_cfs": float(latest["value"]) if latest.get("value") else None,
                    "datetime": latest.get("dateTime", ""),
                }
            )
        return events
    except Exception as exc:
        logger.warning("USGS streamflow fetch failed: %s", exc)
        return []


def fetch_flood_events(
    bbox: list[list[float]],
    center_lat: float,
    center_lon: float,
) -> dict[str, Any]:
    """Fetch flood events for the AOI, routing by geolocation.

    Parameters
    ----------
    bbox : list of [lon, lat] pairs
        AOI bounding box corners from mosaic._coords_to_bbox.
    center_lat, center_lon : float
        AOI centroid for geolocation routing.

    Returns
    -------
    dict with "source", "events" list, and "count".
    """
    lons = [p[0] for p in bbox]
    lats = [p[1] for p in bbox]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    if _is_uk(center_lat, center_lon):
        events = fetch_ea_floods(min_lat, min_lon, max_lat, max_lon)
        return {"source": "ea_flood_monitoring", "events": events, "count": len(events)}

    if _is_us(center_lat, center_lon):
        events = fetch_usgs_streamflow(min_lat, min_lon, max_lat, max_lon)
        return {"source": "usgs_nwis", "events": events, "count": len(events)}

    logger.info("No flood data source for centroid %.2f, %.2f", center_lat, center_lon)
    return {"source": "none", "events": [], "count": 0}

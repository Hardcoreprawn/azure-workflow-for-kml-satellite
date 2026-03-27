"""EUDR utilities — coordinate conversion, WDPA check, land-cover query (M4 §4.9–4.12)."""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from treesight.constants import DEFAULT_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# KML template fragments
_KML_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{doc_name}</name>
"""
_KML_FOOTER = """\
</Document>
</kml>
"""

_PLACEMARK_POLYGON = """\
  <Placemark>
    <name>{name}</name>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>{coordinates}</coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
"""

_PLACEMARK_POINT_BUFFER = """\
  <Placemark>
    <name>{name}</name>
    <description>Buffer radius: {radius_m}m around ({lon}, {lat})</description>
    <Polygon>
      <outerBoundaryIs>
        <LinearRing>
          <coordinates>{coordinates}</coordinates>
        </LinearRing>
      </outerBoundaryIs>
    </Polygon>
  </Placemark>
"""

# Earth radius for buffer computation
_EARTH_RADIUS_M = 6_371_000.0


def coords_to_kml(
    plots: list[dict[str, Any]],
    *,
    doc_name: str = "EUDR Plots",
    buffer_m: float = 100.0,
) -> str:
    """Convert a list of coordinate plots to a KML document.

    Each plot can be either:
    - A point: ``{"name": "Plot A", "lon": 2.35, "lat": 48.86}``
      → buffered into a circular polygon with ``buffer_m`` radius.
    - A polygon: ``{"name": "Plot B", "coordinates": [[lon,lat], ...]}``
      → written as-is.

    Returns a valid KML string.
    """
    parts = [_KML_HEADER.format(doc_name=_xml_escape(doc_name))]

    for plot in plots:
        name = _xml_escape(plot.get("name", "Unnamed"))
        if "coordinates" in plot:
            # Polygon mode
            ring = plot["coordinates"]
            # Close ring if needed
            if ring and ring[0] != ring[-1]:
                ring = [*list(ring), ring[0]]
            coord_str = " ".join(f"{c[0]},{c[1]},0" for c in ring)
            parts.append(_PLACEMARK_POLYGON.format(name=name, coordinates=coord_str))
        elif "lon" in plot and "lat" in plot:
            # Point → buffer circle
            lon, lat = float(plot["lon"]), float(plot["lat"])
            radius = float(plot.get("radius_m", buffer_m))
            ring = _point_buffer(lon, lat, radius)
            coord_str = " ".join(f"{c[0]:.6f},{c[1]:.6f},0" for c in ring)
            parts.append(
                _PLACEMARK_POINT_BUFFER.format(
                    name=name,
                    radius_m=radius,
                    lon=lon,
                    lat=lat,
                    coordinates=coord_str,
                )
            )
        else:
            logger.warning("Skipping plot with no coordinates or lon/lat: %s", name)

    parts.append(_KML_FOOTER)
    return "".join(parts)


def _point_buffer(lon: float, lat: float, radius_m: float, segments: int = 32) -> list[list[float]]:
    """Generate a circular polygon around a point (approximation on WGS84)."""
    if radius_m <= 0:
        raise ValueError(f"radius_m must be positive, got {radius_m!r}")
    if segments < 3:
        raise ValueError(f"segments must be >= 3, got {segments!r}")

    lat_r = math.radians(lat)
    # Clamp latitude away from the poles to avoid division by zero in cos(lat).
    pole_epsilon = 1e-6
    max_lat_r = (math.pi / 2) - pole_epsilon
    safe_lat_r = max(min(lat_r, max_lat_r), -max_lat_r)
    cos_safe_lat = math.cos(safe_lat_r)

    ring: list[list[float]] = []
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        dlat = (radius_m / _EARTH_RADIUS_M) * math.cos(angle)
        dlon = (radius_m / (_EARTH_RADIUS_M * cos_safe_lat)) * math.sin(angle)
        ring.append([lon + math.degrees(dlon), lat + math.degrees(dlat)])
    return ring


def _xml_escape(text: str) -> str:
    """Minimal XML escaping for KML text content."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# WDPA protected-area overlap check (M4 §4.12)
# ---------------------------------------------------------------------------

_WDPA_API_BASE = "https://api.protectedplanet.net/v3"


def check_wdpa_overlap(
    lon: float,
    lat: float,
    *,
    token: str = "",
) -> dict[str, Any]:
    """Check if a point falls within a WDPA protected area.

    Uses the Protected Planet API v3 point-in-polygon query.
    Returns metadata about overlapping protected areas, or an empty
    result if none found or if the API is unavailable.

    Parameters
    ----------
    lon, lat : float
        Centroid coordinates (WGS84).
    token : str
        Protected Planet API token.  Falls back to env var
        ``WDPA_API_TOKEN`` if not supplied.
    """
    import os

    api_token = token or os.environ.get("WDPA_API_TOKEN", "")
    if not api_token:
        logger.info("WDPA check skipped — no API token configured")
        return {"checked": False, "reason": "no_api_token", "protected_areas": []}

    try:
        resp = httpx.get(
            f"{_WDPA_API_BASE}/protected_areas/search",
            params={
                "latitude": lat,
                "longitude": lon,
                "per_page": 5,
            },
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        areas = data.get("protected_areas", [])

        results: list[dict[str, Any]] = []
        for area in areas:
            attrs = area.get("attributes", {})
            results.append(
                {
                    "name": attrs.get("name", "Unknown"),
                    "wdpa_id": area.get("id"),
                    "designation": attrs.get("designation", {}).get("name", ""),
                    "iucn_category": attrs.get("iucn_category", {}).get("name", ""),
                    "status": attrs.get("legal_status", ""),
                    "country": attrs.get("countries", [{}])[0].get("name", "")
                    if attrs.get("countries")
                    else "",
                }
            )

        return {
            "checked": True,
            "is_protected": len(results) > 0,
            "protected_areas": results,
            "query_point": {"lon": lon, "lat": lat},
        }

    except Exception:
        logger.warning("WDPA API check failed", exc_info=True)
        return {
            "checked": False,
            "reason": "api_error",
            "protected_areas": [],
            "query_point": {"lon": lon, "lat": lat},
        }


# ---------------------------------------------------------------------------
# ESA WorldCover land-cover class lookup (M4 §4.11)
# ---------------------------------------------------------------------------

# ESA WorldCover 10m — class codes and labels
WORLDCOVER_CLASSES: dict[int, str] = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}


def query_worldcover(
    bbox: list[float],
    *,
    stub_mode: bool = False,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Query ESA WorldCover 2021 and sample land-cover classes within a bbox.

    Searches the ``esa-worldcover`` collection on Planetary Computer,
    then reads the ``map`` asset (a COG of uint8 class codes at 10 m)
    windowed to *bbox* and computes per-class pixel counts and
    area percentages.

    Parameters
    ----------
    bbox : list[float]
        ``[min_lon, min_lat, max_lon, max_lat]`` in WGS84.
    stub_mode : bool
        When ``True``, return a synthetic result without network calls
        (used in unit tests).
    """
    if stub_mode:
        return _stub_worldcover(bbox)

    stac_url = "https://planetarycomputer.microsoft.com/api/stac/v1"

    def _do_query(client: httpx.Client) -> dict[str, Any]:
        try:
            # 1. Find the WorldCover STAC item covering this bbox.
            search_resp = client.post(
                f"{stac_url}/search",
                json={
                    "collections": ["esa-worldcover"],
                    "bbox": bbox,
                    "limit": 1,
                    "sortby": [{"field": "datetime", "direction": "desc"}],
                },
            )
            search_resp.raise_for_status()
            items = search_resp.json().get("features", [])

            if not items:
                return {
                    "available": False,
                    "reason": "no_worldcover_data",
                    "bbox": bbox,
                }

            item = items[0]
            item_id = item.get("id", "")
            map_asset = item.get("assets", {}).get("map")
            if not map_asset:
                return {
                    "available": False,
                    "reason": "no_map_asset",
                    "bbox": bbox,
                }

            # 2. Sign the COG URL and read the bbox window.
            breakdown = _sample_worldcover_cog(map_asset["href"], bbox)

            center_lon = (bbox[0] + bbox[2]) / 2
            center_lat = (bbox[1] + bbox[3]) / 2

            return {
                "available": True,
                "item_id": item_id,
                "collection": "esa-worldcover",
                "center": {"lon": center_lon, "lat": center_lat},
                "bbox": bbox,
                "land_cover": breakdown,
            }

        except Exception:
            logger.warning("WorldCover query failed", exc_info=True)
            return {
                "available": False,
                "reason": "query_error",
                "bbox": bbox,
            }

    if http_client is None:
        with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS) as client:
            return _do_query(client)
    return _do_query(http_client)


def _sample_worldcover_cog(
    href: str,
    bbox: list[float],
) -> dict[str, Any]:
    """Read the WorldCover COG windowed to *bbox* and return class breakdown.

    Returns a dict with ``total_pixels``, ``classes`` (list of per-class
    dicts with ``code``, ``label``, ``pixel_count``, ``area_pct``), and
    ``dominant_class``.
    """
    import numpy as np
    import planetary_computer
    import rasterio
    from rasterio.windows import from_bounds as window_from_bounds

    signed_href = planetary_computer.sign_url(href)

    with rasterio.open(signed_href) as src:
        window = window_from_bounds(
            bbox[0],
            bbox[1],
            bbox[2],
            bbox[3],
            transform=src.transform,
        )
        window = window.intersection(
            rasterio.windows.Window(0, 0, src.width, src.height),
        )
        data = src.read(1, window=window)

    total = int(data.size)
    if total == 0:
        return {"total_pixels": 0, "classes": [], "dominant_class": None}

    unique, counts = np.unique(data, return_counts=True)

    # Exclude nodata (code 0) from the denominator so percentages sum to 100%.
    nodata_mask = unique == 0
    nodata_count = int(counts[nodata_mask].sum()) if nodata_mask.any() else 0
    valid_total = total - nodata_count
    if valid_total == 0:
        return {"total_pixels": total, "classes": [], "dominant_class": None}

    classes: list[dict[str, Any]] = []
    for code, count in zip(unique, counts, strict=True):
        code_int = int(code)
        if code_int == 0:
            continue  # nodata
        label = WORLDCOVER_CLASSES.get(code_int, f"Unknown ({code_int})")
        classes.append(
            {
                "code": code_int,
                "label": label,
                "pixel_count": int(count),
                "area_pct": round(100.0 * int(count) / valid_total, 2),
            }
        )

    # Sort by pixel count descending.
    classes.sort(key=lambda c: c["pixel_count"], reverse=True)
    dominant = classes[0]["label"] if classes else None

    return {
        "total_pixels": total,
        "classes": classes,
        "dominant_class": dominant,
    }


def _stub_worldcover(bbox: list[float]) -> dict[str, Any]:
    """Return a synthetic WorldCover result for unit tests."""
    center_lon = (bbox[0] + bbox[2]) / 2
    center_lat = (bbox[1] + bbox[3]) / 2
    return {
        "available": True,
        "item_id": "ESA_WorldCover_10m_2021_v200_STUB",
        "collection": "esa-worldcover",
        "center": {"lon": center_lon, "lat": center_lat},
        "bbox": bbox,
        "land_cover": {
            "total_pixels": 10000,
            "classes": [
                {"code": 10, "label": "Tree cover", "pixel_count": 6500, "area_pct": 65.0},
                {"code": 40, "label": "Cropland", "pixel_count": 2000, "area_pct": 20.0},
                {"code": 30, "label": "Grassland", "pixel_count": 1000, "area_pct": 10.0},
                {"code": 50, "label": "Built-up", "pixel_count": 500, "area_pct": 5.0},
            ],
            "dominant_class": "Tree cover",
        },
    }

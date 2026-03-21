"""Geometry computation — AOI preparation (§3.1 step 2)."""

from __future__ import annotations

import math

from treesight.config import AOI_BUFFER_M, AOI_MAX_AREA_HA
from treesight.constants import EARTH_RADIUS_M, METRES_PER_DEGREE_LATITUDE
from treesight.models.aoi import AOI
from treesight.models.feature import Feature


def prepare_aoi(feature: Feature, buffer_m: float | None = None) -> AOI:
    """Compute bounding box, buffered bbox, geodesic area, centroid from a Feature."""
    buf = buffer_m if buffer_m is not None else AOI_BUFFER_M
    exterior = feature.exterior_coords

    bbox = _compute_bbox(exterior)
    buffered_bbox = _buffer_bbox(bbox, buf)
    area_ha = _geodesic_area_ha(exterior)
    centroid = _centroid(exterior)

    area_warning = ""
    if area_ha > AOI_MAX_AREA_HA:
        area_warning = f"Area {area_ha:.1f} ha exceeds max {AOI_MAX_AREA_HA:.1f} ha"

    return AOI(
        feature_name=feature.name,
        source_file=feature.source_file,
        feature_index=feature.feature_index,
        exterior_coords=feature.exterior_coords,
        interior_coords=feature.interior_coords,
        bbox=bbox,
        buffered_bbox=buffered_bbox,
        area_ha=area_ha,
        centroid=centroid,
        buffer_m=buf,
        crs="EPSG:4326",
        metadata=feature.metadata,
        area_warning=area_warning,
    )


def _compute_bbox(coords: list[list[float]]) -> list[float]:
    if not coords:
        return [0.0, 0.0, 0.0, 0.0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return [min(lons), min(lats), max(lons), max(lats)]


def _buffer_bbox(bbox: list[float], buffer_m: float) -> list[float]:
    """Expand bounding box by buffer_m metres in all directions."""
    if buffer_m <= 0:
        return bbox[:]
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_offset = buffer_m / METRES_PER_DEGREE_LATITUDE
    mid_lat = (min_lat + max_lat) / 2.0
    lon_offset = buffer_m / (METRES_PER_DEGREE_LATITUDE * math.cos(math.radians(mid_lat)))
    return [
        min_lon - lon_offset,
        min_lat - lat_offset,
        max_lon + lon_offset,
        max_lat + lat_offset,
    ]


def _geodesic_area_ha(coords: list[list[float]]) -> float:
    """Compute geodesic area of a polygon in hectares using the Shoelace formula on a sphere."""
    if len(coords) < 3:
        return 0.0
    try:
        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        area_m2, _ = geod.polygon_area_perimeter(lons, lats)
        return abs(area_m2) / 10_000.0
    except ImportError:
        # Fallback: simple spherical excess (less accurate)
        return _spherical_area_ha(coords)


def _spherical_area_ha(coords: list[list[float]]) -> float:
    """Approximate area using spherical excess. Fallback when pyproj unavailable."""
    earth_radius_m = EARTH_RADIUS_M
    n = len(coords)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        j = (i + 1) % n
        lon1, lat1 = math.radians(coords[i][0]), math.radians(coords[i][1])
        lon2, lat2 = math.radians(coords[j][0]), math.radians(coords[j][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    area_m2 = abs(total * earth_radius_m * earth_radius_m / 2.0)
    return area_m2 / 10_000.0


def square_bbox(
    bbox: list[float],
    padding_pct: float = 10.0,
) -> list[float]:
    """Create a square viewing window around an AOI bounding box.

    This is a **rendering** concern — the square frame determines the
    extent of output imagery tiles so they display consistently in a
    grid / comparison UI.  The user's actual polygon geometry is
    preserved unchanged for all analytical operations (NDVI, change
    detection, area calculations).

    Takes ``[min_lon, min_lat, max_lon, max_lat]`` and returns a square
    bbox centred on the original, sized to wholly contain the AOI
    plus *padding_pct* % on each side.

    Parameters
    ----------
    bbox : list[float]
        ``[min_lon, min_lat, max_lon, max_lat]`` in EPSG:4326.
    padding_pct : float
        Percentage padding to add on each side (default 10%).

    Returns
    -------
    list[float]
        Square ``[min_lon, min_lat, max_lon, max_lat]``.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2.0
    mid_lon = (min_lon + max_lon) / 2.0

    # Convert to approximate metres for square calculation
    lat_span_m = (max_lat - min_lat) * METRES_PER_DEGREE_LATITUDE
    lon_span_m = (max_lon - min_lon) * METRES_PER_DEGREE_LATITUDE * math.cos(math.radians(mid_lat))

    # Square side = max of both spans + padding
    side_m = max(lat_span_m, lon_span_m) * (1 + padding_pct / 100.0)
    half_side_m = side_m / 2.0

    # Back to degrees
    half_lat = half_side_m / METRES_PER_DEGREE_LATITUDE
    cos_lat = math.cos(math.radians(mid_lat))
    half_lon = half_side_m / (METRES_PER_DEGREE_LATITUDE * cos_lat) if cos_lat > 0 else half_lat

    return [
        mid_lon - half_lon,
        mid_lat - half_lat,
        mid_lon + half_lon,
        mid_lat + half_lat,
    ]


def _centroid(coords: list[list[float]]) -> list[float]:
    if not coords:
        return [0.0, 0.0]
    # Exclude closing point if ring is closed
    pts = coords if coords[0] != coords[-1] else coords[:-1]
    n = len(pts)
    if n == 0:
        return [0.0, 0.0]
    avg_lon = sum(c[0] for c in pts) / n
    avg_lat = sum(c[1] for c in pts) / n
    return [avg_lon, avg_lat]

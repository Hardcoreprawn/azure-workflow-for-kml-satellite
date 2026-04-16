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
    area_ha, perimeter_km = _geodesic_area_and_perimeter(exterior)
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
        perimeter_km=perimeter_km,
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


def _geodesic_area_and_perimeter(coords: list[list[float]]) -> tuple[float, float]:
    """Compute geodesic area (ha) and perimeter (km) from a single Geod call."""
    if len(coords) < 3:
        return 0.0, 0.0
    try:
        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        area_m2, perimeter_m = geod.polygon_area_perimeter(lons, lats)
        return abs(area_m2) / 10_000.0, abs(perimeter_m) / 1_000.0
    except ImportError:
        return _spherical_area_ha(coords), _haversine_perimeter_km(coords)


def transform_bbox(
    bbox: list[float],
    src_crs: str,
    dst_crs: str,
) -> tuple[float, float, float, float]:
    """Reproject a bounding box between CRS."""
    if src_crs == dst_crs:
        return (bbox[0], bbox[1], bbox[2], bbox[3])

    from pyproj import Transformer

    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    x_min, y_min = transformer.transform(bbox[0], bbox[1])
    x_max, y_max = transformer.transform(bbox[2], bbox[3])
    return (
        min(x_min, x_max),
        min(y_min, y_max),
        max(x_min, x_max),
        max(y_min, y_max),
    )


def _haversine_perimeter_km(coords: list[list[float]]) -> float:
    """Approximate perimeter using Haversine distance. Fallback when pyproj unavailable."""
    if len(coords) < 2:
        return 0.0
    # Ensure ring closure: add closing segment if first != last
    ring = list(coords)
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    total = 0.0
    for i in range(len(ring) - 1):
        lon1, lat1 = math.radians(ring[i][0]), math.radians(ring[i][1])
        lon2, lat2 = math.radians(ring[i + 1][0]), math.radians(ring[i + 1][1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        total += EARTH_RADIUS_M * c
    return total / 1_000.0


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
    """Arithmetic mean of exterior ring vertices.

    Note: for concave or complex polygons the result may fall outside
    the polygon boundary.  This is acceptable for our use-case (map
    centering) but should not be treated as a guaranteed interior point.
    """
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


# ---------------------------------------------------------------------------
# Spatial clustering (#581)
# ---------------------------------------------------------------------------

_DEFAULT_CLUSTER_EPS_KM = 25.0


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine distance in kilometres between two WGS-84 points."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return (EARTH_RADIUS_M / 1_000) * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _union_find_clusters(n: int, edges: list[tuple[int, int]]) -> list[int]:
    """Return root labels for *n* items connected by *edges* (Union-Find)."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    return [find(i) for i in range(n)]


def cluster_aois(
    aois: list[dict],
    eps_km: float = _DEFAULT_CLUSTER_EPS_KM,
) -> list[list[dict]]:
    """Group AOIs into spatial clusters using DBSCAN-style single-linkage.

    Each AOI is represented by the centroid of its ``coords``.  AOIs
    within *eps_km* kilometres of any member of a cluster are merged
    into that cluster (transitive linkage).

    Parameters
    ----------
    aois:
        List of AOI dicts, each with a ``coords`` key (list of ``[lon, lat]``).
    eps_km:
        Maximum inter-centroid distance (km) to link two AOIs.

    Returns
    -------
    list[list[dict]]
        Groups of AOI dicts.  Order within and across groups is stable.
    """
    if not aois:
        return []

    n = len(aois)

    # Compute centroids; AOIs without coords get None
    centroids: list[list[float] | None] = []
    for aoi in aois:
        coords = aoi.get("coords", [])
        centroids.append(_centroid(coords) if coords else None)

    # Build edge list of pairs within eps_km
    edges: list[tuple[int, int]] = []
    for i in range(n):
        ci = centroids[i]
        if ci is None:
            continue
        for j in range(i + 1, n):
            cj = centroids[j]
            if cj is None:
                continue
            if _haversine_km(ci[0], ci[1], cj[0], cj[1]) <= eps_km:
                edges.append((i, j))

    labels = _union_find_clusters(n, edges)

    # Collect clusters preserving insertion order
    clusters_map: dict[int, list[dict]] = {}
    for i in range(n):
        clusters_map.setdefault(labels[i], []).append(aois[i])

    return list(clusters_map.values())

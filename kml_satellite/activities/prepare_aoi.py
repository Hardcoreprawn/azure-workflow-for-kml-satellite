"""AOI processing activity function.

Computes bounding box, buffered bounding box, geodesic area in hectares,
and centroid for each polygon feature extracted from a KML file.

The buffered bounding box is computed by projecting to a local metric CRS
(UTM), applying the buffer, and projecting back to WGS 84  --  never by
adding degrees (PID 7.4.3: Buffer arithmetic).

Engineering standards (PID 7.4):
- Zero-assumption: validates coordinates, buffer range, polygon viability
- Fail loudly: every error produces an actionable message with context
- Defensive geometry: area reasonableness checks, metric-CRS buffer
- Explicit units: hectares for area, metres for buffer (PID 7.4.5)
- Observability: structured logging of all AOI metadata (FR-2.3)

References:
- FR-1.6 (bounding box), FR-1.7 (area in hectares), FR-1.8 (centroid)
- FR-2.1 (buffered bounding box, configurable 50-200 m)
- FR-2.3 (log AOI metadata)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kml_satellite.models.aoi import AOI

if TYPE_CHECKING:
    from kml_satellite.models.feature import Feature

logger = logging.getLogger("kml_satellite.activities.prepare_aoi")

# ---------------------------------------------------------------------------
# Constants (PID 7.4.5: No magic numbers)
# ---------------------------------------------------------------------------

MIN_BUFFER_M = 50.0
MAX_BUFFER_M = 200.0
DEFAULT_BUFFER_M = 100.0
DEFAULT_AREA_THRESHOLD_HA = 10_000.0

# Minimum coordinates for a valid polygon (3 distinct + closure)
MIN_COORDS_FOR_POLYGON = 3

# Square metres per hectare (PID 7.4.5: explicit unit conversion)
SQ_METRES_PER_HECTARE = 10_000.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AOIError(Exception):
    """Raised when AOI processing encounters an unrecoverable error."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prepare_aoi(
    feature: Feature,
    *,
    buffer_m: float = DEFAULT_BUFFER_M,
    area_threshold_ha: float = DEFAULT_AREA_THRESHOLD_HA,
) -> AOI:
    """Process a Feature into an AOI with geometry metadata.

    Args:
        feature: A parsed KML Feature (from ``parse_kml`` activity).
        buffer_m: Buffer distance in metres (default 100, range 50-200).
        area_threshold_ha: Area threshold in hectares for reasonableness
            warning (default 10,000).

    Returns:
        An AOI dataclass with bbox, buffered_bbox, area_ha, centroid.

    Raises:
        AOIError: If the feature has insufficient coordinates or
            invalid buffer configuration.
    """
    exterior = feature.exterior_coords
    interior = feature.interior_coords

    # Validate inputs at the boundary (PID 7.4.1)
    _validate_coords(exterior, feature.name)

    # Compute geometry properties
    bbox = compute_bbox(exterior)
    buffered_bbox = compute_buffered_bbox(exterior, buffer_m=buffer_m)
    area_ha = compute_geodesic_area_ha(exterior, interior_rings=interior)
    centroid = compute_centroid(exterior, interior_rings=interior)

    # Area reasonableness check (PID 7.4.3)
    area_warning = ""
    if area_ha > area_threshold_ha:
        area_warning = (
            f"Area {area_ha:.1f} ha exceeds threshold of "
            f"{area_threshold_ha:.0f} ha for feature '{feature.name}'"
        )
        logger.warning(area_warning)

    # Structured logging of AOI metadata (FR-2.3)
    logger.info(
        "AOI prepared | feature=%s | area=%.2f ha | buffer=%.0f m | "
        "bbox=[%.4f, %.4f, %.4f, %.4f] | centroid=(%.4f, %.4f) | source=%s",
        feature.name,
        area_ha,
        buffer_m,
        *bbox,
        *centroid,
        feature.source_file,
    )

    return AOI(
        feature_name=feature.name,
        source_file=feature.source_file,
        feature_index=feature.feature_index,
        exterior_coords=exterior,
        interior_coords=interior,
        bbox=bbox,
        buffered_bbox=buffered_bbox,
        area_ha=area_ha,
        centroid=centroid,
        buffer_m=buffer_m,
        crs=feature.crs,
        metadata=dict(feature.metadata),
        area_warning=area_warning,
    )


# ---------------------------------------------------------------------------
# Bounding Box (FR-1.6)
# ---------------------------------------------------------------------------


def compute_bbox(
    coords: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Compute a tight bounding box from polygon coordinates.

    Args:
        coords: Exterior ring as list of ``(lon, lat)`` tuples.

    Returns:
        ``(min_lon, min_lat, max_lon, max_lat)``

    Raises:
        AOIError: If coordinates are empty or insufficient.
    """
    _validate_coords(coords, "bbox computation")
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


# ---------------------------------------------------------------------------
# Buffered Bounding Box (FR-2.1)
# ---------------------------------------------------------------------------


def compute_buffered_bbox(
    coords: list[tuple[float, float]],
    *,
    buffer_m: float = DEFAULT_BUFFER_M,
) -> tuple[float, float, float, float]:
    """Compute a bounding box expanded by a metric buffer.

    Projects the bbox corners to a local UTM CRS, applies the buffer,
    and projects back to WGS 84. This ensures accurate metric distances
    (PID 7.4.3: buffer arithmetic must not use degrees).

    Args:
        coords: Exterior ring as list of ``(lon, lat)`` tuples.
        buffer_m: Buffer distance in metres (range 50-200).

    Returns:
        ``(min_lon, min_lat, max_lon, max_lat)`` with buffer applied.

    Raises:
        AOIError: If buffer is outside allowed range or coords invalid.
    """
    if buffer_m < MIN_BUFFER_M or buffer_m > MAX_BUFFER_M:
        msg = f"Buffer {buffer_m} m is outside allowed range [{MIN_BUFFER_M}, {MAX_BUFFER_M}] m"
        raise AOIError(msg)

    bbox = compute_bbox(coords)
    min_lon, min_lat, max_lon, max_lat = bbox

    # Determine the appropriate UTM zone from the centroid
    centre_lon = (min_lon + max_lon) / 2
    centre_lat = (min_lat + max_lat) / 2
    utm_crs = _get_utm_crs(centre_lon, centre_lat)

    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_wgs = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)

    # Project all four bbox corners to UTM to capture true extrema
    # in projected space (convergence/distortion can shift extrema)
    utm_sw_x, utm_sw_y = to_utm.transform(min_lon, min_lat)
    utm_nw_x, utm_nw_y = to_utm.transform(min_lon, max_lat)
    utm_se_x, utm_se_y = to_utm.transform(max_lon, min_lat)
    utm_ne_x, utm_ne_y = to_utm.transform(max_lon, max_lat)

    utm_xs = (utm_sw_x, utm_nw_x, utm_se_x, utm_ne_x)
    utm_ys = (utm_sw_y, utm_nw_y, utm_se_y, utm_ne_y)

    utm_min_x = min(utm_xs)
    utm_max_x = max(utm_xs)
    utm_min_y = min(utm_ys)
    utm_max_y = max(utm_ys)

    # Apply buffer in metres
    utm_min_x -= buffer_m
    utm_min_y -= buffer_m
    utm_max_x += buffer_m
    utm_max_y += buffer_m

    # Project back to WGS 84
    buf_min_lon, buf_min_lat = to_wgs.transform(utm_min_x, utm_min_y)
    buf_max_lon, buf_max_lat = to_wgs.transform(utm_max_x, utm_max_y)

    return (buf_min_lon, buf_min_lat, buf_max_lon, buf_max_lat)


# ---------------------------------------------------------------------------
# Geodesic Area (FR-1.7)
# ---------------------------------------------------------------------------


def compute_geodesic_area_ha(
    exterior_coords: list[tuple[float, float]],
    interior_rings: list[list[tuple[float, float]]] | None = None,
) -> float:
    """Compute geodesic polygon area in hectares.

    Uses pyproj.Geod on the WGS 84 ellipsoid for accurate area
    regardless of latitude. Returns absolute area (winding-order agnostic).

    Args:
        exterior_coords: Exterior ring as list of ``(lon, lat)`` tuples.
        interior_rings: Interior rings (holes) to subtract.

    Returns:
        Area in hectares (PID 7.4.5: explicit unit).

    Raises:
        AOIError: If coordinates are empty.
    """
    _validate_coords(exterior_coords, "area computation")

    from pyproj import Geod

    geod = Geod(ellps="WGS84")

    # Separate lons and lats for pyproj
    ext_lons = [c[0] for c in exterior_coords]
    ext_lats = [c[1] for c in exterior_coords]

    # Geod.polygon_area_perimeter returns (area_m2, perimeter_m)
    area_m2, _perimeter = geod.polygon_area_perimeter(ext_lons, ext_lats)
    total_area = abs(area_m2)

    # Subtract holes
    if interior_rings:
        for ring in interior_rings:
            if len(ring) >= MIN_COORDS_FOR_POLYGON:
                hole_lons = [c[0] for c in ring]
                hole_lats = [c[1] for c in ring]
                hole_area_m2, _ = geod.polygon_area_perimeter(hole_lons, hole_lats)
                total_area -= abs(hole_area_m2)

    # Convert to hectares (PID 7.4.5: no implicit unit conversions)
    return total_area / SQ_METRES_PER_HECTARE


# ---------------------------------------------------------------------------
# Centroid (FR-1.8)
# ---------------------------------------------------------------------------


def compute_centroid(
    coords: list[tuple[float, float]],
    interior_rings: list[list[tuple[float, float]]] | None = None,
) -> tuple[float, float]:
    """Compute the centroid of a polygon using Shapely.

    Args:
        coords: Exterior ring as list of ``(lon, lat)`` tuples.
        interior_rings: Interior rings (holes) to subtract.

    Returns:
        Centroid as ``(lon, lat)`` tuple.

    Raises:
        AOIError: If coordinates are empty or polygon is invalid.
    """
    _validate_coords(coords, "centroid computation")

    from shapely.geometry import Polygon

    holes = interior_rings if interior_rings else None
    poly = Polygon(coords, holes=holes)
    if poly.is_empty:
        msg = "Cannot compute centroid of an empty polygon"
        raise AOIError(msg)

    centroid = poly.centroid
    return (centroid.x, centroid.y)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_coords(coords: list[tuple[float, float]], context: str) -> None:
    """Validate that coordinates are non-empty and sufficient for a polygon.

    Raises:
        AOIError: If coordinates are empty or too few for a polygon.
    """
    if not coords:
        msg = f"Empty coordinates  --  no coordinates provided for {context}"
        raise AOIError(msg)
    if len(coords) < MIN_COORDS_FOR_POLYGON:
        msg = (
            f"Insufficient coordinates for {context}: "
            f"need at least {MIN_COORDS_FOR_POLYGON}, got {len(coords)}"
        )
        raise AOIError(msg)


def _get_utm_crs(lon: float, lat: float) -> str:
    """Determine the UTM CRS for a given WGS 84 coordinate.

    Returns an EPSG code like ``"EPSG:32610"`` (UTM zone 10N) or
    ``"EPSG:32710"`` (UTM zone 10S).

    Args:
        lon: Longitude in degrees.
        lat: Latitude in degrees.

    Returns:
        UTM CRS EPSG string.
    """
    # UTM zone number: 1-based, 6° wide, starting at -180°
    zone_number = int((lon + 180) / 6) + 1
    # Clamp to valid range 1-60
    zone_number = max(1, min(60, zone_number))

    if lat >= 0:
        # Northern hemisphere: EPSG:326xx
        return f"EPSG:{32600 + zone_number}"
    # Southern hemisphere: EPSG:327xx
    return f"EPSG:{32700 + zone_number}"

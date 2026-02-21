"""Validation helpers for KML parsing (Issue #60).

Responsibilities:
- XML structure and KML namespace validation
- Coordinate bounds checking (WGS 84)
- Polygon ring structure validation (closure, vertex count)
- Shapely geometry validity checks and repair
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kml_satellite.activities.parse_kml._constants import (
    KML_NAMESPACE,
    MAX_LATITUDE,
    MAX_LONGITUDE,
    MIN_LATITUDE,
    MIN_LONGITUDE,
    MIN_POLYGON_VERTICES,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("kml_satellite.activities.parse_kml")


# ---------------------------------------------------------------------------
# Exceptions (public API, re-exported from __init__)
# ---------------------------------------------------------------------------

from kml_satellite.core.exceptions import PipelineError  # noqa: E402


class KmlParseError(PipelineError):
    """Raised when a KML file cannot be parsed."""

    default_stage = "parse_kml"
    default_code = "KML_PARSE_FAILED"


class KmlValidationError(KmlParseError):
    """Raised when a KML file is structurally valid but contains invalid data."""

    default_code = "KML_VALIDATION_FAILED"


class InvalidCoordinateError(KmlValidationError):
    """Raised when coordinates are outside valid WGS 84 bounds."""

    default_code = "KML_COORDINATE_INVALID"


# ---------------------------------------------------------------------------
# XML / KML namespace validation
# ---------------------------------------------------------------------------


def validate_xml(kml_path: Path) -> None:
    """Validate that the file is well-formed XML with KML namespace.

    Raises:
        KmlParseError: If the file is not valid XML or lacks KML namespace.
    """
    from lxml import etree  # type: ignore[attr-defined]

    try:
        content = kml_path.read_bytes()
    except OSError as exc:
        msg = f"Cannot read KML file: {exc}"
        raise KmlParseError(msg) from exc

    if not content.strip():
        msg = "KML file is empty"
        raise KmlParseError(msg)

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError as exc:
        msg = f"Not valid XML: {exc}"
        raise KmlParseError(msg) from exc

    tag = root.tag
    if f"{{{KML_NAMESPACE}}}" not in tag and "kml" not in tag.lower():
        msg = f"Not a KML file — root element is <{tag}>"
        raise KmlParseError(msg)


# ---------------------------------------------------------------------------
# Coordinate validation
# ---------------------------------------------------------------------------


def validate_coordinates(coords: list[tuple[float, float]], placemark_name: str) -> None:
    """Validate that all coordinates are within WGS 84 bounds.

    Raises:
        InvalidCoordinateError: If any coordinate is out of bounds.
    """
    for lon, lat in coords:
        if not (MIN_LONGITUDE <= lon <= MAX_LONGITUDE):
            msg = (
                f"Longitude {lon} out of WGS 84 range [{MIN_LONGITUDE}, {MAX_LONGITUDE}] "
                f"in Placemark '{placemark_name}'"
            )
            raise InvalidCoordinateError(msg)
        if not (MIN_LATITUDE <= lat <= MAX_LATITUDE):
            msg = (
                f"Latitude {lat} out of WGS 84 range [{MIN_LATITUDE}, {MAX_LATITUDE}] "
                f"in Placemark '{placemark_name}'"
            )
            raise InvalidCoordinateError(msg)


# ---------------------------------------------------------------------------
# Polygon ring validation
# ---------------------------------------------------------------------------


def validate_polygon_ring(
    coords: list[tuple[float, float]], placemark_name: str
) -> list[tuple[float, float]]:
    """Validate a polygon ring has enough vertices and is closed.

    Returns the (possibly auto-closed) coordinate list.

    Raises:
        KmlValidationError: If the ring has fewer than 3 distinct points.
    """
    if len(coords) < 3:
        msg = (
            f"Polygon ring has only {len(coords)} point(s), need at least 3 "
            f"in Placemark '{placemark_name}'"
        )
        raise KmlValidationError(msg)

    # Auto-close if first != last (PID 7.4.3: handle unclosed rings)
    if coords[0] != coords[-1]:
        logger.warning(
            "Auto-closing unclosed ring in Placemark '%s'",
            placemark_name,
        )
        coords = [*coords, coords[0]]

    if len(coords) < MIN_POLYGON_VERTICES:
        msg = (
            f"Polygon ring has fewer than {MIN_POLYGON_VERTICES} vertices "
            f"(including closure) in Placemark '{placemark_name}'"
        )
        raise KmlValidationError(msg)

    # Check for degenerate: all distinct points
    distinct = set(coords)
    if len(distinct) < 3:
        msg = f"Polygon ring has fewer than 3 distinct points in Placemark '{placemark_name}'"
        raise KmlValidationError(msg)

    return coords


# ---------------------------------------------------------------------------
# Shapely geometry validation
# ---------------------------------------------------------------------------


def validate_shapely_geometry(
    exterior: list[tuple[float, float]],
    interior: list[list[tuple[float, float]]],
    placemark_name: str,
) -> None:
    """Validate geometry using shapely.

    Checks ``is_valid`` and attempts ``make_valid()`` if needed.

    Raises:
        KmlValidationError: If the geometry is invalid and cannot be repaired.
    """
    from shapely.geometry import Polygon
    from shapely.validation import make_valid

    try:
        poly = Polygon(exterior, interior)
    except Exception as exc:
        msg = f"Cannot create polygon for Placemark '{placemark_name}': {exc}"
        raise KmlValidationError(msg) from exc

    if not poly.is_valid:
        logger.warning(
            "Invalid geometry in Placemark '%s', attempting make_valid()",
            placemark_name,
        )
        repaired = make_valid(poly)
        if repaired.is_empty:
            msg = f"Geometry is empty after make_valid() for Placemark '{placemark_name}'"
            raise KmlValidationError(msg)
        if repaired.geom_type not in ("Polygon", "MultiPolygon"):
            msg = (
                f"Geometry became {repaired.geom_type} after make_valid() "
                f"for Placemark '{placemark_name}'"
            )
            raise KmlValidationError(msg)
        poly = repaired
        logger.info(
            "Geometry repaired for Placemark '%s'",
            placemark_name,
        )

    if poly.area == 0:
        msg = f"Zero-area polygon in Placemark '{placemark_name}'"
        raise KmlValidationError(msg)

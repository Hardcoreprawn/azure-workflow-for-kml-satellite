"""KML parsing activity function.

Parses a KML file and extracts polygon features with geometry and metadata.
Uses fiona (OGR KML driver) as the primary parser, with an lxml fallback
for edge cases where OGR fails (e.g. SchemaData typed metadata).

Engineering standards (PID 7.4):
- Zero-assumption input handling: validates XML, namespace, CRS, coordinates
- Fail loudly: every error produces an actionable message with context
- Defensive geometry: validate with shapely, check coordinate bounds
- Explicit: type hints, named constants, no magic strings
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from kml_satellite.models.feature import Feature

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("kml_satellite.activities.parse_kml")

# ---------------------------------------------------------------------------
# Constants (PID 7.4.5: No magic strings)
# ---------------------------------------------------------------------------

KML_NAMESPACE = "http://www.opengis.net/kml/2.2"

# WGS 84 coordinate bounds (PID 7.4.3: Coordinate sanity checks)
MIN_LONGITUDE = -180.0
MAX_LONGITUDE = 180.0
MIN_LATITUDE = -90.0
MAX_LATITUDE = 90.0

# Minimum vertices for a valid polygon (3 distinct + closing = 4)
MIN_POLYGON_VERTICES = 4


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class KmlParseError(Exception):
    """Raised when a KML file cannot be parsed."""


class KmlValidationError(KmlParseError):
    """Raised when a KML file is structurally valid but contains invalid data."""


class InvalidCoordinateError(KmlValidationError):
    """Raised when coordinates are outside valid WGS 84 bounds."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_kml_file(kml_path: Path | str, *, source_filename: str = "") -> list[Feature]:
    """Parse a KML file and extract polygon features.

    Attempts fiona (OGR KML driver) first, falls back to lxml for
    edge cases. Validates XML structure, KML namespace, geometry,
    and coordinate bounds.

    Args:
        kml_path: Path to the KML file on disk (or bytes-like).
        source_filename: Original filename for metadata (defaults to path stem).

    Returns:
        List of Feature objects — one per polygon Placemark.
        Empty list if the file contains no polygon features.

    Raises:
        KmlParseError: If the file is not valid XML or KML.
        KmlValidationError: If the file is valid KML but contains
            invalid data (e.g. unsupported CRS).
        InvalidCoordinateError: If any coordinate is outside WGS 84 bounds.
    """
    from pathlib import Path

    kml_path = Path(kml_path)
    if not source_filename:
        source_filename = kml_path.name

    logger.info("Parsing KML file: %s", source_filename)

    # Step 1: Validate XML and KML namespace
    _validate_xml(kml_path)

    # Step 2: Try fiona first, fall back to lxml
    try:
        features = _parse_with_fiona(kml_path, source_filename)
    except Exception as fiona_err:
        logger.warning(
            "Fiona parse failed for %s, trying lxml fallback: %s",
            source_filename,
            fiona_err,
        )
        features = _parse_with_lxml(kml_path, source_filename)

    logger.info(
        "Parsed %d polygon feature(s) from %s",
        len(features),
        source_filename,
    )
    return features


# ---------------------------------------------------------------------------
# XML / KML validation
# ---------------------------------------------------------------------------


def _validate_xml(kml_path: Path) -> None:
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

    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError as exc:
        msg = f"Not valid XML: {exc}"
        raise KmlParseError(msg) from exc

    # Check for KML namespace
    tag = root.tag
    if f"{{{KML_NAMESPACE}}}" not in tag and "kml" not in tag.lower():
        msg = f"Not a KML file — root element is <{tag}>"
        raise KmlParseError(msg)


# ---------------------------------------------------------------------------
# Coordinate validation
# ---------------------------------------------------------------------------


def _validate_coordinates(coords: list[tuple[float, float]], placemark_name: str) -> None:
    """Validate that all coordinates are within WGS 84 bounds.

    Args:
        coords: List of (longitude, latitude) tuples.
        placemark_name: Name of the Placemark for error messages.

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


def _validate_polygon_ring(
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
# Fiona-based parser (primary)
# ---------------------------------------------------------------------------


def _parse_with_fiona(kml_path: Path, source_filename: str) -> list[Feature]:
    """Parse KML using fiona (OGR KML driver).

    Fiona returns GeoJSON-like dicts with geometry and properties.
    Only Polygon and MultiPolygon geometry types are extracted.
    """
    import fiona

    features: list[Feature] = []

    with fiona.open(str(kml_path), driver="KML") as collection:
        # CRS check: fiona reports the CRS from the driver
        crs_str = _extract_crs_from_fiona(collection)

        for idx, record in enumerate(collection):
            geom = record.get("geometry")
            props = record.get("properties", {}) or {}

            if geom is None:
                continue

            geom_type = geom.get("type", "")

            if geom_type == "Polygon":
                feature = _fiona_polygon_to_feature(geom, props, source_filename, idx, crs_str)
                if feature is not None:
                    features.append(feature)

            elif geom_type == "MultiPolygon":
                # Fan-out: each polygon in a MultiPolygon becomes a separate Feature
                coords_list = geom.get("coordinates", [])
                for sub_idx, poly_coords in enumerate(coords_list):
                    sub_geom = {"type": "Polygon", "coordinates": poly_coords}
                    feature = _fiona_polygon_to_feature(
                        sub_geom,
                        props,
                        source_filename,
                        idx,
                        crs_str,
                        sub_index=sub_idx,
                    )
                    if feature is not None:
                        features.append(feature)
            # Skip non-polygon types (Point, LineString, etc.)

    return features


def _extract_crs_from_fiona(collection: object) -> str:
    """Extract CRS string from a fiona collection.

    KML is always WGS 84 per specification. We verify this.

    Raises:
        KmlValidationError: If the CRS is not WGS 84.
    """
    crs = getattr(collection, "crs", None)
    if crs is None:
        return "EPSG:4326"

    # Fiona returns CRS as a dict or CRS object
    epsg = getattr(crs, "to_epsg", lambda: None)()

    if epsg is not None and epsg != 4326:
        msg = f"Unexpected CRS: EPSG:{epsg} (expected EPSG:4326 for KML)"
        raise KmlValidationError(msg)

    return "EPSG:4326"


def _fiona_polygon_to_feature(
    geom: dict[str, object],
    props: dict[str, object],
    source_filename: str,
    feature_index: int,
    crs: str,
    *,
    sub_index: int | None = None,
) -> Feature | None:
    """Convert a fiona polygon geometry + properties into a Feature.

    Returns None if validation fails (logs a warning).
    """
    coords_list = geom.get("coordinates", [])
    if not isinstance(coords_list, list | tuple) or not coords_list:
        return None

    # GeoJSON Polygon: first ring is exterior, rest are interior (holes)
    exterior_raw = coords_list[0]
    interior_raw = coords_list[1:] if len(coords_list) > 1 else []

    # Convert to (lon, lat) tuples, dropping altitude
    exterior = _coords_to_tuples(exterior_raw)
    interior = [_coords_to_tuples(ring) for ring in interior_raw]

    # Extract Placemark metadata
    placemark_name = str(props.get("Name", "") or props.get("name", "") or "")
    description = str(props.get("Description", "") or props.get("description", "") or "")

    # Build display name
    display_name = placemark_name or f"Feature {feature_index}"
    if sub_index is not None:
        display_name = f"{display_name} (part {sub_index})"

    # Validate coordinates
    _validate_coordinates(exterior, display_name)
    for hole_ring in interior:
        _validate_coordinates(hole_ring, f"{display_name} (hole)")

    # Validate polygon ring structure
    exterior = _validate_polygon_ring(exterior, display_name)
    interior = [_validate_polygon_ring(ring, f"{display_name} (hole)") for ring in interior]

    # Validate geometry with shapely
    _validate_shapely_geometry(exterior, interior, display_name)

    # Extract ExtendedData metadata from fiona properties
    # Fiona puts KML ExtendedData/Data values into properties dict
    metadata = _extract_metadata_from_props(props)

    return Feature(
        name=placemark_name,
        description=description,
        exterior_coords=exterior,
        interior_coords=interior,
        crs=crs,
        metadata=metadata,
        source_file=source_filename,
        feature_index=feature_index,
    )


# ---------------------------------------------------------------------------
# lxml-based parser (fallback)
# ---------------------------------------------------------------------------


def _parse_with_lxml(kml_path: Path, source_filename: str) -> list[Feature]:
    """Parse KML using lxml by walking the element tree.

    Handles cases where fiona's OGR KML driver fails, such as:
    - SchemaData typed metadata
    - Nested Folder hierarchies
    """
    from lxml import etree  # type: ignore[attr-defined]

    content = kml_path.read_bytes()
    root: Any = etree.fromstring(content)
    ns = {"kml": KML_NAMESPACE}

    features: list[Feature] = []
    placemarks: list[Any] = root.findall(".//kml:Placemark", ns)

    for idx, pm in enumerate(placemarks):
        polygons = pm.findall(".//kml:Polygon", ns)
        if not polygons:
            continue

        # Extract metadata common to the Placemark
        name_elem = pm.find("kml:name", ns)
        desc_elem = pm.find("kml:description", ns)
        placemark_name = (name_elem.text or "").strip() if name_elem is not None else ""
        description = (desc_elem.text or "").strip() if desc_elem is not None else ""
        metadata = _extract_extended_data_lxml(pm, ns)

        for poly_idx, polygon in enumerate(polygons):
            exterior, interior = _parse_polygon_lxml(polygon, ns)
            if not exterior:
                continue

            display_name = placemark_name or f"Feature {idx}"
            if len(polygons) > 1:
                display_name = f"{display_name} (polygon {poly_idx})"

            # Validate
            _validate_coordinates(exterior, display_name)
            for hole_ring in interior:
                _validate_coordinates(hole_ring, f"{display_name} (hole)")

            exterior = _validate_polygon_ring(exterior, display_name)
            interior = [
                _validate_polygon_ring(ring, f"{display_name} (hole)") for ring in interior
            ]

            _validate_shapely_geometry(exterior, interior, display_name)

            features.append(
                Feature(
                    name=placemark_name,
                    description=description,
                    exterior_coords=exterior,
                    interior_coords=interior,
                    crs="EPSG:4326",
                    metadata=metadata,
                    source_file=source_filename,
                    feature_index=idx,
                )
            )

    return features


def _parse_polygon_lxml(
    polygon_elem: Any, ns: dict[str, str]
) -> tuple[list[tuple[float, float]], list[list[tuple[float, float]]]]:
    """Parse a KML Polygon element via lxml, returning exterior + interior coords."""
    from lxml import etree  # type: ignore[attr-defined]

    if not isinstance(polygon_elem, etree._Element):
        return ([], [])

    outer_boundary = polygon_elem.find("kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)
    exterior: list[tuple[float, float]] = []
    if outer_boundary is not None and outer_boundary.text:
        exterior = _parse_coordinates_text(outer_boundary.text.strip())

    interior: list[list[tuple[float, float]]] = []
    for inner_boundary in polygon_elem.findall(
        "kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", ns
    ):
        if inner_boundary.text:
            ring = _parse_coordinates_text(inner_boundary.text.strip())
            if ring:
                interior.append(ring)

    return (exterior, interior)


def _parse_coordinates_text(text: str) -> list[tuple[float, float]]:
    """Parse KML coordinate text (``lon,lat,alt lon,lat,alt ...``) to (lon, lat) tuples."""
    coords: list[tuple[float, float]] = []
    for token in text.split():
        parts = token.strip().split(",")
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                coords.append((lon, lat))
            except ValueError:
                continue
    return coords


def _extract_extended_data_lxml(placemark_elem: Any, ns: dict[str, str]) -> dict[str, str]:
    """Extract ExtendedData/Data key-value pairs from a Placemark element."""
    from lxml import etree  # type: ignore[attr-defined]

    metadata: dict[str, str] = {}
    if not isinstance(placemark_elem, etree._Element):
        return metadata

    for data_elem in placemark_elem.findall("kml:ExtendedData/kml:Data", ns):
        key = data_elem.get("name", "")
        value_elem = data_elem.find("kml:value", ns)
        if key and value_elem is not None and value_elem.text:
            metadata[key] = value_elem.text.strip()

    return metadata


# ---------------------------------------------------------------------------
# Geometry validation (shapely)
# ---------------------------------------------------------------------------


def _validate_shapely_geometry(
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
        logger.info(
            "Geometry repaired for Placemark '%s'",
            placemark_name,
        )

    if poly.area == 0:
        msg = f"Zero-area polygon in Placemark '{placemark_name}'"
        raise KmlValidationError(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coords_to_tuples(raw_coords: object) -> list[tuple[float, float]]:
    """Convert GeoJSON-style coordinate arrays to (lon, lat) tuples.

    Drops altitude (third element) if present.
    """
    if not isinstance(raw_coords, list | tuple):
        return []
    return [(float(c[0]), float(c[1])) for c in raw_coords if len(c) >= 2]  # type: ignore[arg-type]


def _extract_metadata_from_props(props: dict[str, object]) -> dict[str, str]:
    """Extract meaningful metadata from fiona properties.

    Fiona maps KML ExtendedData/Data values into the properties dict.
    Standard KML properties (Name, Description) are excluded here since
    they are already captured as Feature fields.
    """
    skip_keys = {
        "name",
        "description",
        "timestamp",
        "begin",
        "end",
        "altitudemode",
        "tessellate",
        "extrude",
        "visibility",
        "draworder",
        "icon",
        "snippet",
    }
    metadata: dict[str, str] = {}
    for key, value in props.items():
        if key.lower() in skip_keys:
            continue
        if value is not None and str(value).strip():
            metadata[key] = str(value).strip()
    return metadata

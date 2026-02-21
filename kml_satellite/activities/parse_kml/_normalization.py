"""Coordinate and metadata normalization helpers for KML parsing (Issue #60).

Responsibilities:
- Convert raw coordinate arrays to clean (lon, lat) tuples
- Extract metadata from fiona properties (untyped ExtendedData)
- Extract metadata from lxml ExtendedData elements (typed + untyped)
- Parse KML coordinate text strings
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kml_satellite.activities.parse_kml._validation import KmlValidationError

if TYPE_CHECKING:
    from lxml.etree import _Element

# ---------------------------------------------------------------------------
# Coordinate normalization
# ---------------------------------------------------------------------------


def coords_to_tuples(raw_coords: object) -> list[tuple[float, float]]:
    """Convert GeoJSON-style coordinate arrays to (lon, lat) tuples.

    Drops altitude (third element) if present.

    Raises:
        KmlValidationError: If any coordinate element is malformed.
    """
    if not isinstance(raw_coords, list | tuple):
        return []
    coords: list[tuple[float, float]] = []
    for idx, c in enumerate(raw_coords):
        if not isinstance(c, list | tuple):
            msg = (
                f"Malformed coordinate at index {idx}: expected list/tuple, got {type(c).__name__}"
            )
            raise KmlValidationError(msg)
        if len(c) < 2:
            msg = (
                f"Malformed coordinate at index {idx}: expected at least 2 elements, got {len(c)}"
            )
            raise KmlValidationError(msg)
        try:
            lon = float(c[0])
            lat = float(c[1])
        except (TypeError, ValueError) as exc:
            msg = (
                f"Malformed coordinate at index {idx}: cannot convert to float "
                f"(lon={c[0]!r}, lat={c[1]!r})"
            )
            raise KmlValidationError(msg) from exc
        coords.append((lon, lat))
    return coords


# ---------------------------------------------------------------------------
# Fiona metadata extraction
# ---------------------------------------------------------------------------

# Standard KML properties that fiona maps to properties dict — excluded
# because they are captured as Feature.name / Feature.description.
_FIONA_SKIP_KEYS = frozenset(
    {
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
)


def extract_metadata_from_props(props: dict[str, object]) -> dict[str, str]:
    """Extract meaningful metadata from fiona properties.

    Standard KML properties (Name, Description, etc.) are excluded
    since they are captured as Feature fields directly.
    """
    metadata: dict[str, str] = {}
    for key, value in props.items():
        if key.lower() in _FIONA_SKIP_KEYS:
            continue
        if value is not None and str(value).strip():
            metadata[key] = str(value).strip()
    return metadata


# ---------------------------------------------------------------------------
# lxml metadata extraction
# ---------------------------------------------------------------------------


def extract_extended_data_lxml(placemark_elem: _Element, ns: dict[str, str]) -> dict[str, str]:
    """Extract ExtendedData metadata from a Placemark element.

    Handles both KML metadata patterns:
    - ``ExtendedData/Data/value`` — untyped key-value pairs.
    - ``ExtendedData/SchemaData/SimpleData`` — typed fields defined by a
      ``<Schema>`` element (PID FR-1.10, M-1.4).
    """
    from lxml import etree  # type: ignore[attr-defined]

    metadata: dict[str, str] = {}
    if not isinstance(placemark_elem, etree._Element):
        return metadata

    # Pattern 1: ExtendedData/Data/value (untyped)
    for data_elem in placemark_elem.findall("kml:ExtendedData/kml:Data", ns):
        key = data_elem.get("name", "")
        value_elem = data_elem.find("kml:value", ns)
        if key and value_elem is not None and value_elem.text:
            metadata[key] = value_elem.text.strip()

    # Pattern 2: ExtendedData/SchemaData/SimpleData (typed via Schema)
    for schema_data in placemark_elem.findall("kml:ExtendedData/kml:SchemaData", ns):
        for simple_data in schema_data.findall("kml:SimpleData", ns):
            key = simple_data.get("name", "")
            if key and simple_data.text:
                metadata[key] = simple_data.text.strip()

    return metadata


# ---------------------------------------------------------------------------
# KML coordinate text parsing
# ---------------------------------------------------------------------------


def parse_coordinates_text(text: str) -> list[tuple[float, float]]:
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

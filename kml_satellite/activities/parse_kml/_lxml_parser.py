"""lxml-based KML parser (fallback) — Issue #60.

Parses KML files by walking the lxml element tree. Handles cases where
fiona's OGR KML driver fails, such as SchemaData typed metadata and
nested Folder hierarchies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from kml_satellite.activities.parse_kml._constants import KML_NAMESPACE
from kml_satellite.activities.parse_kml._normalization import (
    extract_extended_data_lxml,
    parse_coordinates_text,
)
from kml_satellite.activities.parse_kml._validation import (
    InvalidCoordinateError,
    KmlValidationError,
    validate_coordinates,
    validate_polygon_ring,
    validate_shapely_geometry,
)
from kml_satellite.models.feature import Feature

if TYPE_CHECKING:
    from pathlib import Path

    from lxml.etree import _Element

logger = logging.getLogger("kml_satellite.activities.parse_kml")


def parse_with_lxml(kml_path: Path, source_filename: str) -> list[Feature]:
    """Parse KML using lxml by walking the element tree.

    Handles cases where fiona's OGR KML driver fails, such as:
    - SchemaData typed metadata
    - Nested Folder hierarchies
    """
    from lxml import etree  # type: ignore[attr-defined]

    content = kml_path.read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root: _Element = etree.fromstring(content, parser=parser)
    ns = {"kml": KML_NAMESPACE}

    features: list[Feature] = []
    placemarks: list[_Element] = root.findall(".//kml:Placemark", ns)

    for idx, pm in enumerate(placemarks):
        polygons = pm.findall(".//kml:Polygon", ns)
        if not polygons:
            continue

        name_elem = pm.find("kml:name", ns)
        desc_elem = pm.find("kml:description", ns)
        placemark_name = (name_elem.text or "").strip() if name_elem is not None else ""
        description = (desc_elem.text or "").strip() if desc_elem is not None else ""
        metadata = extract_extended_data_lxml(pm, ns)

        for poly_idx, polygon in enumerate(polygons):
            display_name = placemark_name or f"Feature {idx}"
            if len(polygons) > 1:
                display_name = f"{display_name} (part {poly_idx})"

            try:
                exterior, interior = _parse_polygon_lxml(polygon, ns)

                if not exterior:
                    raise KmlValidationError(
                        f"Placemark '{display_name}' has a <Polygon> with no exterior "
                        f"coordinates (missing or empty outerBoundaryIs/LinearRing)."
                    )

                validate_coordinates(exterior, display_name)
                for hole_ring in interior:
                    validate_coordinates(hole_ring, f"{display_name} (hole)")

                exterior = validate_polygon_ring(exterior, display_name)
                interior = [
                    validate_polygon_ring(ring, f"{display_name} (hole)") for ring in interior
                ]

                validate_shapely_geometry(exterior, interior, display_name)

            except (KmlValidationError, InvalidCoordinateError) as exc:
                logger.warning(
                    "Skipping invalid feature '%s' in %s: %s",
                    display_name,
                    source_filename,
                    exc,
                )
                continue

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_polygon_lxml(
    polygon_elem: _Element, ns: dict[str, str]
) -> tuple[list[tuple[float, float]], list[list[tuple[float, float]]]]:
    """Parse a KML Polygon element via lxml, returning exterior + interior coords."""
    from lxml import etree  # type: ignore[attr-defined]

    if not isinstance(polygon_elem, etree._Element):
        return ([], [])

    outer_boundary = polygon_elem.find("kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", ns)
    exterior: list[tuple[float, float]] = []
    if outer_boundary is not None and outer_boundary.text:
        exterior = parse_coordinates_text(outer_boundary.text.strip())

    interior: list[list[tuple[float, float]]] = []
    for inner_boundary in polygon_elem.findall(
        "kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", ns
    ):
        if inner_boundary.text:
            ring = parse_coordinates_text(inner_boundary.text.strip())
            if ring:
                interior.append(ring)

    return (exterior, interior)

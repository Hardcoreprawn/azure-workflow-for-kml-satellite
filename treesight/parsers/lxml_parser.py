"""Fallback KML parser using lxml (§7.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from treesight.log import logger
from treesight.models.feature import Feature
from treesight.parsers import ensure_closed as _ensure_closed

if TYPE_CHECKING:
    from lxml.etree import _Element  # pyright: ignore[reportPrivateUsage]

KML_NS = "{http://www.opengis.net/kml/2.2}"


def parse_kml_lxml(kml_bytes: bytes, source_file: str = "") -> list[Feature]:
    """Parse KML bytes using lxml. Fallback when Fiona/GDAL is unavailable."""
    from lxml import etree

    # Secure parser: disable external entities and network access to prevent XXE
    parser = etree.XMLParser(resolve_entities=False, no_network=True, dtd_validation=False)
    root: _Element = etree.fromstring(kml_bytes, parser=parser)
    features: list[Feature] = []

    for placemark in root.iter(f"{KML_NS}Placemark"):
        name = _text(placemark, f"{KML_NS}name") or f"Unnamed Feature {len(features)}"
        description = _text(placemark, f"{KML_NS}description") or ""
        metadata = _parse_extended_data(placemark)

        for polygon in placemark.iter(f"{KML_NS}Polygon"):
            exterior, interior = _parse_polygon(polygon)
            if len(exterior) < 3:
                logger.warning("Skipping polygon with < 3 coords: %s", name)
                continue
            exterior = _ensure_closed(exterior)
            interior = [_ensure_closed(ring) for ring in interior]
            features.append(
                Feature(
                    name=name,
                    description=description,
                    exterior_coords=exterior,
                    interior_coords=interior,
                    crs="EPSG:4326",
                    metadata=metadata,
                    source_file=source_file,
                    feature_index=len(features),
                )
            )

    return features


def _parse_polygon(
    polygon: _Element,
) -> tuple[list[list[float]], list[list[list[float]]]]:
    """Extract exterior and interior coordinate rings from a KML Polygon element."""
    exterior: list[list[float]] = []
    interior: list[list[list[float]]] = []

    outer = polygon.find(f"{KML_NS}outerBoundaryIs/{KML_NS}LinearRing/{KML_NS}coordinates")
    if outer is not None and outer.text:
        exterior = _parse_coordinates(outer.text)

    for inner_elem in polygon.findall(
        f"{KML_NS}innerBoundaryIs/{KML_NS}LinearRing/{KML_NS}coordinates"
    ):
        if inner_elem.text:
            ring = _parse_coordinates(inner_elem.text)
            if ring:
                interior.append(ring)

    return exterior, interior


def _parse_coordinates(text: str) -> list[list[float]]:
    """Parse a KML coordinate string into a list of [lon, lat] pairs."""
    coords: list[list[float]] = []
    for token in text.strip().split():
        parts = token.strip().split(",")
        if len(parts) >= 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
                coords.append([lon, lat])
            except ValueError:
                continue
    return coords


def _parse_extended_data(placemark: _Element) -> dict[str, str]:
    """Extract ExtendedData key-value pairs from a Placemark element."""
    metadata: dict[str, str] = {}
    ext = placemark.find(f"{KML_NS}ExtendedData")
    if ext is None:
        return metadata
    for data in ext.findall(f"{KML_NS}Data"):
        key = data.get("name", "")
        val_elem = data.find(f"{KML_NS}value")
        if key and val_elem is not None and val_elem.text:
            metadata[key] = val_elem.text
    return metadata


def _text(elem: _Element, tag: str) -> str:
    """Extract text content from a child element, or empty string if absent."""
    child = elem.find(tag)
    return child.text.strip() if child is not None and child.text else ""

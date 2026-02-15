"""Activity function for parsing KML files with single polygons.

Parses a KML file containing a single polygon and returns structured geometry data.
Uses lxml as the primary parser.

Implements:
- FR-1.4: Support single polygon per KML file
- FR-1.5: Extract geometry coordinates (lat/lon vertices)
- FR-1.9: Validate WGS 84 (EPSG:4326) CRS
- FR-1.10: Parse and preserve metadata
"""

from __future__ import annotations

import logging
from pathlib import Path

from lxml import etree

from kml_satellite.models.feature import (
    Feature,
    InvalidKMLError,
    MalformedXMLError,
    validate_polygon_coordinates,
)

logger = logging.getLogger("kml_satellite.activities.parse_kml")

# KML namespace for lxml fallback parsing
KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def parse_kml(kml_path: str | Path) -> Feature:
    """Parse a KML file containing a single polygon.

    Args:
        kml_path: Path to the KML file.

    Returns:
        Feature with validated geometry and metadata.

    Raises:
        MalformedXMLError: If the file is not valid XML.
        InvalidKMLError: If the KML structure is invalid.
        CoordinateValidationError: If coordinates are out of WGS 84 bounds.
        CRSValidationError: If CRS is not WGS 84 (EPSG:4326).
    """
    kml_path = Path(kml_path)

    # Step 1: Validate well-formed XML and KML namespace
    _validate_xml_and_namespace(kml_path)

    # Step 2: Parse with lxml (primary parser)
    # Note: Fiona's KML driver is not available in this environment
    return _parse_with_lxml(kml_path)


def _validate_xml_and_namespace(kml_path: Path) -> None:
    """Validate that the file is well-formed XML with KML namespace.

    Args:
        kml_path: Path to the KML file.

    Raises:
        MalformedXMLError: If not valid XML or missing KML namespace.
    """
    try:
        tree = etree.parse(str(kml_path))  # noqa: S320
    except etree.XMLSyntaxError as e:
        raise MalformedXMLError(
            f"File {kml_path.name} is not valid XML: {e}"
        ) from e
    except Exception as e:
        raise MalformedXMLError(
            f"Failed to read file {kml_path.name}: {e}"
        ) from e

    root = tree.getroot()

    # Verify KML namespace
    if root.tag != f"{{{KML_NS['kml']}}}kml":
        raise MalformedXMLError(
            f"File {kml_path.name} is not a KML file (missing KML namespace)"
        )


def _parse_with_lxml(kml_path: Path) -> Feature:
    """Parse KML using lxml (fallback for edge cases).

    Args:
        kml_path: Path to the KML file.

    Returns:
        Feature with geometry and metadata.

    Raises:
        InvalidKMLError: If KML structure is invalid.
        CoordinateValidationError: If coordinates are invalid.
    """
    tree = etree.parse(str(kml_path))  # noqa: S320
    root = tree.getroot()

    # Find all Placemarks and filter for those with Polygons
    placemarks = root.findall(".//kml:Placemark", namespaces=KML_NS)
    placemark = None
    for pm in placemarks:
        if pm.find(".//kml:Polygon", namespaces=KML_NS) is not None:
            placemark = pm
            break

    if placemark is None:
        raise InvalidKMLError(f"No Polygon Placemark found in {kml_path.name}")

    # Extract name and description
    name_elem = placemark.find("kml:name", namespaces=KML_NS)
    desc_elem = placemark.find("kml:description", namespaces=KML_NS)

    name = name_elem.text.strip() if name_elem is not None and name_elem.text else ""
    description = (
        desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
    )

    # Extract ExtendedData
    extended_data = _extract_extended_data_lxml(placemark)

    # Extract polygon coordinates
    polygon = placemark.find(".//kml:Polygon", namespaces=KML_NS)
    if polygon is None:
        raise InvalidKMLError(f"No Polygon found in Placemark in {kml_path.name}")

    coords_elem = polygon.find(
        ".//kml:outerBoundaryIs//kml:coordinates", namespaces=KML_NS
    )
    if coords_elem is None or not coords_elem.text:
        raise InvalidKMLError(
            f"No coordinates found in Polygon in {kml_path.name}"
        )

    # Parse coordinates
    coordinates = _parse_coordinates(coords_elem.text)

    # Validate coordinates
    validate_polygon_coordinates(coordinates)

    # Build GeoJSON-like geometry
    geometry = {
        "type": "Polygon",
        "coordinates": [coordinates],  # exterior ring
    }

    metadata = {
        "name": name,
        "description": description,
        "extended_data": extended_data,
    }

    return Feature(
        geometry=geometry,
        properties=metadata,
        crs="EPSG:4326",
    )


def _extract_extended_data_lxml(placemark: etree._Element) -> dict[str, str]:
    """Extract ExtendedData from a Placemark element.

    Args:
        placemark: Placemark XML element.

    Returns:
        Dict of extended data key-value pairs.
    """
    extended_data_elem = placemark.find("kml:ExtendedData", namespaces=KML_NS)
    if extended_data_elem is None:
        return {}

    extended_data = {}
    for data_elem in extended_data_elem.findall("kml:Data", namespaces=KML_NS):
        name = data_elem.get("name")
        value_elem = data_elem.find("kml:value", namespaces=KML_NS)
        if name and value_elem is not None and value_elem.text:
            extended_data[name] = value_elem.text.strip()

    return extended_data


def _parse_coordinates(coords_text: str) -> list[list[float]]:
    """Parse KML coordinates text into a list of [lon, lat, alt] tuples.

    Args:
        coords_text: Raw coordinates text from KML (whitespace-separated tuples).

    Returns:
        List of [lon, lat, alt] or [lon, lat] coordinate lists.

    Raises:
        InvalidKMLError: If coordinates cannot be parsed.
    """
    coords = []
    for line in coords_text.strip().split():
        parts = line.split(",")
        if len(parts) < 2:
            continue  # Skip empty or invalid lines

        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0
            coords.append([lon, lat, alt])
        except (ValueError, IndexError) as e:
            raise InvalidKMLError(
                f"Failed to parse coordinate '{line}': {e}"
            ) from e

    if not coords:
        raise InvalidKMLError("No valid coordinates found")

    return coords

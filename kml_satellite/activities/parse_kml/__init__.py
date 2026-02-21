"""KML parsing activity — composable pipeline (Issue #60).

Parses a KML file and extracts polygon features with geometry and metadata.
Uses fiona (OGR KML driver) as the primary parser, with an lxml fallback
for edge cases where OGR fails (e.g. SchemaData typed metadata).

The parsing pipeline is split into focused stages:
- **_validation**: XML/KML check, coordinate bounds, polygon ring, shapely
- **_normalization**: raw coord → tuple, metadata extraction (fiona + lxml)
- **_fiona_parser**: primary parser using fiona/OGR
- **_lxml_parser**: fallback parser using lxml element tree

Supported KML structures (M-1.3 + M-1.4):
- Single polygon Placemarks
- Multiple Placemarks (multi-feature fan-out)
- MultiGeometry containing multiple Polygons
- Nested Folder hierarchies (recursive traversal)
- Inner boundaries (holes / exclusion zones)
- ExtendedData/Data and Schema/SchemaData typed metadata
- Degenerate geometries: auto-close, make_valid, partial failure

Engineering standards (PID 7.4):
- Zero-assumption input handling: validates XML, namespace, CRS, coordinates
- Fail loudly: every error produces an actionable message with context
- Defensive geometry: validate with shapely, check coordinate bounds
- Graceful degradation: one bad feature does not crash remaining (PID 7.4.2)
- Explicit: type hints, named constants, no magic strings
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
from kml_satellite.activities.parse_kml._fiona_parser import parse_with_fiona
from kml_satellite.activities.parse_kml._lxml_parser import parse_with_lxml
from kml_satellite.activities.parse_kml._normalization import (
    coords_to_tuples,
    extract_extended_data_lxml,
    extract_metadata_from_props,
    parse_coordinates_text,
)
from kml_satellite.activities.parse_kml._validation import (
    InvalidCoordinateError,
    KmlParseError,
    KmlValidationError,
    validate_coordinates,
    validate_polygon_ring,
    validate_shapely_geometry,
    validate_xml,
)

if TYPE_CHECKING:
    from pathlib import Path

    from kml_satellite.models.feature import Feature

logger = logging.getLogger("kml_satellite.activities.parse_kml")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "KML_NAMESPACE",
    "MAX_LATITUDE",
    "MAX_LONGITUDE",
    "MIN_LATITUDE",
    "MIN_LONGITUDE",
    "MIN_POLYGON_VERTICES",
    "InvalidCoordinateError",
    "KmlParseError",
    "KmlValidationError",
    "coords_to_tuples",
    "extract_extended_data_lxml",
    "extract_metadata_from_props",
    "parse_coordinates_text",
    "parse_kml_file",
    "parse_with_fiona",
    "parse_with_lxml",
    "validate_coordinates",
    "validate_polygon_ring",
    "validate_shapely_geometry",
    "validate_xml",
]


def parse_kml_file(kml_path: Path | str, *, source_filename: str = "") -> list[Feature]:
    """Parse a KML file and extract polygon features.

    Attempts fiona (OGR KML driver) first, falls back to lxml for
    edge cases. Validates XML structure, KML namespace, geometry,
    and coordinate bounds.

    Args:
        kml_path: Filesystem path to the KML file on disk (str or pathlib.Path).
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
    validate_xml(kml_path)

    # Step 2: Try fiona first, fall back to lxml
    try:
        features = parse_with_fiona(kml_path, source_filename)
    except (KmlParseError, KmlValidationError, InvalidCoordinateError):
        raise
    except Exception as fiona_err:
        logger.warning(
            "Fiona parse failed for %s, trying lxml fallback: %s",
            source_filename,
            fiona_err,
        )
        features = parse_with_lxml(kml_path, source_filename)

    logger.info(
        "Parsed %d polygon feature(s) from %s",
        len(features),
        source_filename,
    )
    return features

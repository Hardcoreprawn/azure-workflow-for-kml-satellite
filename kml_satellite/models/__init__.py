"""Data models and schemas.

Defines the data structures used throughout the pipeline:
- Feature: Extracted geometry with metadata from KML
- AOI: Area of Interest with bounding box, buffer, area, centroid
- ImageryResult: Satellite imagery acquisition result
- ProcessingMetadata: Per-AOI metadata JSON schema
"""

from kml_satellite.models.feature import (
    CRSValidationError,
    CoordinateValidationError,
    Feature,
    InvalidKMLError,
    KMLParseError,
    MalformedXMLError,
    validate_polygon_coordinates,
    validate_wgs84_coordinate,
)

__all__ = [
    "Feature",
    "CoordinateValidationError",
    "CRSValidationError",
    "KMLParseError",
    "MalformedXMLError",
    "InvalidKMLError",
    "validate_wgs84_coordinate",
    "validate_polygon_coordinates",
]

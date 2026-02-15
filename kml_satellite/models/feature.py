"""Data model for parsed KML features.

Represents a single feature extracted from a KML file with validated geometry
and metadata. Used by the parse_kml activity function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Feature:
    """Parsed KML feature with geometry and metadata.

    Attributes:
        geometry: GeoJSON-like geometry dict (type, coordinates).
        properties: Metadata dict with name, description, extended_data.
        crs: Coordinate Reference System (default: EPSG:4326).
    """

    geometry: dict[str, Any]
    properties: dict[str, Any] = field(default_factory=dict)
    crs: str = "EPSG:4326"

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict for passing to Durable Functions orchestrator."""
        return {
            "geometry": self.geometry,
            "properties": self.properties,
            "crs": self.crs,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Feature:
        """Construct from a dict (deserialization from orchestrator context)."""
        return cls(
            geometry=data.get("geometry", {}),
            properties=data.get("properties", {}),
            crs=data.get("crs", "EPSG:4326"),
        )


class CoordinateValidationError(ValueError):
    """Raised when coordinates are out of valid WGS 84 bounds."""


class CRSValidationError(ValueError):
    """Raised when CRS is not WGS 84 (EPSG:4326)."""


class KMLParseError(ValueError):
    """Base exception for KML parsing errors."""


class MalformedXMLError(KMLParseError):
    """Raised when input is not valid XML."""


class InvalidKMLError(KMLParseError):
    """Raised when XML is valid but KML structure is invalid."""


def validate_wgs84_coordinate(lon: float, lat: float) -> None:
    """Validate that coordinates are within WGS 84 bounds.

    Args:
        lon: Longitude value.
        lat: Latitude value.

    Raises:
        CoordinateValidationError: If coordinates are out of bounds.
    """
    if not -180.0 <= lon <= 180.0:
        msg = f"Longitude {lon} is out of valid WGS 84 range [-180, 180]"
        raise CoordinateValidationError(msg)

    if not -90.0 <= lat <= 90.0:
        msg = f"Latitude {lat} is out of valid WGS 84 range [-90, 90]"
        raise CoordinateValidationError(msg)


def validate_polygon_coordinates(coordinates: list[list[float]]) -> None:
    """Validate all coordinates in a polygon ring.

    Args:
        coordinates: List of [lon, lat, alt] or [lon, lat] coordinate tuples.

    Raises:
        CoordinateValidationError: If any coordinate is out of bounds.
    """
    for coord in coordinates:
        if len(coord) < 2:
            msg = f"Invalid coordinate {coord}: must have at least lon, lat"
            raise CoordinateValidationError(msg)
        validate_wgs84_coordinate(coord[0], coord[1])

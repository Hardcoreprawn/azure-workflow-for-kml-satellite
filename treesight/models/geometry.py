"""Immutable polygon geometry used at pipeline and export boundaries."""

from __future__ import annotations

import math
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import explain_validity

Position: TypeAlias = tuple[float, float]
LinearRing: TypeAlias = tuple[Position, ...]

_RING_ADAPTER = TypeAdapter(LinearRing)


class PolygonPart(BaseModel):
    """One exterior boundary and its explicitly associated interior holes."""

    model_config = ConfigDict(frozen=True)

    exterior: LinearRing
    holes: tuple[LinearRing, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_polygon(self) -> PolygonPart:
        for ring in (self.exterior, *self.holes):
            _validate_ring_coordinates(ring)

        polygon = Polygon(self.exterior, self.holes)
        if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
            reason = explain_validity(polygon)
            raise ValueError(f"geometry must form a valid polygon: {reason}")
        return self


class PolygonGeometry(BaseModel):
    """A Polygon or MultiPolygon represented as validated immutable parts.

    Each part owns one exterior and zero or more holes. Ring membership is
    explicit and never inferred from coordinate order or winding direction.
    Coordinates use longitude/latitude order in EPSG:4326.
    """

    model_config = ConfigDict(frozen=True)

    parts: tuple[PolygonPart, ...] = Field(min_length=1)
    crs: Literal["EPSG:4326"] = "EPSG:4326"

    @model_validator(mode="after")
    def validate_parts(self) -> PolygonGeometry:
        polygons = [Polygon(part.exterior, part.holes) for part in self.parts]
        geometry = MultiPolygon(polygons)
        if not geometry.is_valid or geometry.is_empty:
            reason = explain_validity(geometry)
            raise ValueError(f"parts must form a valid MultiPolygon: {reason}")
        return self

    @property
    def geometry_type(self) -> Literal["Polygon", "MultiPolygon"]:
        """Return the interoperable GeoJSON type for this geometry."""
        if len(self.parts) == 1:
            return "Polygon"
        return "MultiPolygon"

    def to_geojson(self) -> dict[str, object]:
        """Serialize to GeoJSON coordinates without flattening ring roles."""
        polygons = tuple((part.exterior, *part.holes) for part in self.parts)
        if len(polygons) == 1:
            return {"type": "Polygon", "coordinates": polygons[0]}
        return {"type": "MultiPolygon", "coordinates": polygons}

    @classmethod
    def from_geojson(cls, value: dict[str, object]) -> PolygonGeometry:
        """Parse GeoJSON Polygon or MultiPolygon coordinates."""
        geometry_type = value.get("type")
        coordinates = value.get("coordinates")
        if not isinstance(coordinates, (list, tuple)):
            raise ValueError("GeoJSON polygon coordinates must be an array")

        if geometry_type == "Polygon":
            polygons: tuple[object, ...] = (coordinates,)
        elif geometry_type == "MultiPolygon":
            polygons = tuple(coordinates)
        else:
            raise ValueError("GeoJSON geometry type must be Polygon or MultiPolygon")

        parts = tuple(_polygon_part_from_coordinates(polygon) for polygon in polygons)
        return cls(parts=parts)


def _polygon_part_from_coordinates(value: object) -> PolygonPart:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("GeoJSON polygon part must contain an exterior ring")

    rings = tuple(_RING_ADAPTER.validate_python(ring) for ring in value)
    return PolygonPart(exterior=rings[0], holes=rings[1:])


def _validate_ring_coordinates(ring: LinearRing) -> None:
    if len(ring) < 4 or ring[0] != ring[-1] or len(set(ring[:-1])) < 3:
        raise ValueError("rings must be closed and contain at least three distinct positions")

    for longitude, latitude in ring:
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError("positions must contain finite coordinates")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("positions must be within EPSG:4326 longitude/latitude bounds")

"""Feature domain model (§2.1).

Represents a single polygon extracted from a KML file.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class Feature(BaseModel):
    """A single polygon feature extracted from a KML file.

    Attributes:
        name: Placemark name (e.g. "Block A - Fuji Apple").
        description: Placemark description text.
        exterior_coords: Exterior ring as list of ``[lon, lat]`` pairs.
        interior_coords: Interior rings (holes), each a list of ``[lon, lat]`` pairs.
        crs: Coordinate reference system. Always ``EPSG:4326`` for KML input.
        metadata: Key-value pairs from KML ExtendedData.
        source_file: Name of the source KML file.
        feature_index: Zero-based index within the source file.
    """

    name: str
    description: str = ""
    exterior_coords: list[list[float]] = Field(default_factory=lambda: [])
    interior_coords: list[list[list[float]]] = Field(default_factory=lambda: [])
    crs: str = "EPSG:4326"
    metadata: dict[str, str] = Field(default_factory=dict)
    source_file: str = ""
    feature_index: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def vertex_count(self) -> int:
        """Number of vertices in the exterior ring."""
        return len(self.exterior_coords)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_holes(self) -> bool:
        """Whether the polygon has interior rings (holes)."""
        return len(self.interior_coords) > 0

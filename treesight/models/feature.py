"""Feature domain model (§2.1).

Represents a single polygon extracted from a KML file.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

from treesight.models.geometry import PolygonGeometry


class Feature(BaseModel):
    """A single polygon feature extracted from a KML file.

    Attributes:
        name: Placemark name (e.g. "Block A - Fuji Apple").
        description: Placemark description text.
        geometry: Polygon or MultiPolygon with explicitly associated holes.
        crs: Coordinate reference system. Always ``EPSG:4326`` for KML input.
        metadata: Key-value pairs from KML ExtendedData.
        source_file: Name of the source KML file.
        feature_index: Zero-based index within the source file.
    """

    name: str
    description: str = ""
    geometry: PolygonGeometry
    metadata: dict[str, str] = Field(default_factory=dict)
    source_file: str = ""
    feature_index: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def vertex_count(self) -> int:
        """Number of vertices across all exterior rings."""
        return sum(len(part.outer) for part in self.geometry.parts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_holes(self) -> bool:
        """Whether the polygon has interior rings (holes)."""
        return any(part.inners for part in self.geometry.parts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def crs(self) -> str:
        """Coordinate reference system of the source geometry."""
        return self.geometry.crs

    @computed_field  # type: ignore[prop-decorator]  # Pydantic computed_field wraps @property.
    @property
    def dedup_key(self) -> str:
        """Deterministic key for same-named features in a source file.

        Uniqueness assumes parser-populated ``source_file`` + ``feature_index``.
        """
        source = self.source_file or "<unspecified>"
        return f"{source}:{self.feature_index}"

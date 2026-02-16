"""Data model for a parsed KML feature.

A Feature represents a single polygon extracted from a KML file,
along with any associated metadata (Placemark name, ExtendedData).
This is the output of the parse_kml activity and the input to
the prepare_aoi activity.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Feature:
    """A single polygon feature extracted from a KML file.

    Attributes:
        name: Placemark name (e.g. ``"Block A - Fuji Apple"``).
        description: Placemark description text.
        exterior_coords: Exterior ring coordinates as list of ``(lon, lat)`` tuples.
        interior_coords: Interior ring(s) (holes) as list of lists of ``(lon, lat)`` tuples.
        crs: Coordinate reference system. Always ``"EPSG:4326"`` for valid KML.
        metadata: Key-value pairs from KML ``ExtendedData/Data`` elements.
        source_file: Name of the source KML file this feature was extracted from.
        feature_index: Zero-based index of this feature within the source file.
    """

    name: str
    description: str = ""
    exterior_coords: list[tuple[float, float]] = field(default_factory=list)
    interior_coords: list[list[tuple[float, float]]] = field(default_factory=list)
    crs: str = "EPSG:4326"
    metadata: dict[str, str] = field(default_factory=dict)
    source_file: str = ""
    feature_index: int = 0

    def to_dict(self) -> dict[str, object]:
        """Serialise to a dict for Durable Functions orchestrator input."""
        return {
            "name": self.name,
            "description": self.description,
            "exterior_coords": [list(c) for c in self.exterior_coords],
            "interior_coords": [[list(c) for c in ring] for ring in self.interior_coords],
            "crs": self.crs,
            "metadata": dict(self.metadata),
            "source_file": self.source_file,
            "feature_index": self.feature_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Feature:
        """Deserialise from a Durable Functions dict payload.

        Missing fields are defaulted (for example, an absent ``name``
        becomes ``""``) rather than raising an error.

        Raises:
            TypeError: If field values have unexpected types.
        """
        exterior_raw = data.get("exterior_coords", [])
        if not isinstance(exterior_raw, list):
            msg = f"exterior_coords must be a list, got {type(exterior_raw).__name__}"
            raise TypeError(msg)
        exterior = [tuple(c) for c in exterior_raw]  # type: ignore[arg-type]

        interior_raw = data.get("interior_coords", [])
        if not isinstance(interior_raw, list):
            msg = f"interior_coords must be a list, got {type(interior_raw).__name__}"
            raise TypeError(msg)
        interior = [[tuple(c) for c in ring] for ring in interior_raw]  # type: ignore[arg-type]

        metadata_raw = data.get("metadata", {})
        if not isinstance(metadata_raw, dict):
            msg = f"metadata must be a dict, got {type(metadata_raw).__name__}"
            raise TypeError(msg)

        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            exterior_coords=exterior,
            interior_coords=interior,
            crs=str(data.get("crs", "EPSG:4326")),
            metadata={str(k): str(v) for k, v in metadata_raw.items()},
            source_file=str(data.get("source_file", "")),
            feature_index=int(data.get("feature_index", 0)),  # type: ignore[arg-type]
        )

    @property
    def vertex_count(self) -> int:
        """Total number of vertices in the exterior ring."""
        return len(self.exterior_coords)

    @property
    def has_holes(self) -> bool:
        """Whether this feature has interior boundary (hole) rings."""
        return len(self.interior_coords) > 0

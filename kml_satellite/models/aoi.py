"""Data model for a processed Area of Interest (AOI).

An AOI represents a polygon feature after geometric processing:
bounding box, buffered bounding box, geodesic area, and centroid.
This is the output of the prepare_aoi activity and the input to
the imagery acquisition activities.

References:
- PID FR-1.6 (bounding box), FR-1.7 (area in hectares), FR-1.8 (centroid)
- PID FR-2.1 (buffered bounding box, configurable 50-200 m)
- PID Section 9.2 (Metadata JSON schema  --  geometry block)
- PID 7.4.5 (Explicit units: hectares, metres, EPSG codes)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AOI:
    """A processed Area of Interest derived from a parsed KML polygon.

    All coordinates are WGS 84 (EPSG:4326).  Area is geodesic hectares.
    Buffer distance is in metres.

    Attributes:
        feature_name: Name of the source Feature / Placemark.
        source_file: Name of the source KML file.
        feature_index: Zero-based index of the feature within the KML file.
        exterior_coords: Exterior ring as list of ``(lon, lat)`` tuples.
        interior_coords: Interior rings (holes) as list of lists of ``(lon, lat)`` tuples.
        bbox: Tight bounding box ``(min_lon, min_lat, max_lon, max_lat)``.
        buffered_bbox: Bounding box expanded by ``buffer_m`` metres on each side.
        area_ha: Geodesic polygon area in hectares (explicit unit  --  PID 7.4.5).
        centroid: Polygon centroid as ``(lon, lat)``.
        buffer_m: Buffer distance applied in metres (default 100, range 50-200).
        crs: Coordinate reference system. Always ``"EPSG:4326"`` for KML.
        metadata: Preserved key-value metadata from the KML feature.
        area_warning: Non-empty string if area exceeds the reasonableness threshold.
    """

    feature_name: str
    source_file: str = ""
    feature_index: int = 0
    exterior_coords: list[tuple[float, float]] = field(default_factory=list)
    interior_coords: list[list[tuple[float, float]]] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    buffered_bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    area_ha: float = 0.0
    centroid: tuple[float, float] = (0.0, 0.0)
    buffer_m: float = 100.0
    crs: str = "EPSG:4326"
    metadata: dict[str, str] = field(default_factory=dict)
    area_warning: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialise to a dict for Durable Functions orchestrator transport."""
        return {
            "feature_name": self.feature_name,
            "source_file": self.source_file,
            "feature_index": self.feature_index,
            "exterior_coords": [list(c) for c in self.exterior_coords],
            "interior_coords": [[list(c) for c in ring] for ring in self.interior_coords],
            "bbox": list(self.bbox),
            "buffered_bbox": list(self.buffered_bbox),
            "area_ha": self.area_ha,
            "centroid": list(self.centroid),
            "buffer_m": self.buffer_m,
            "crs": self.crs,
            "metadata": dict(self.metadata),
            "area_warning": self.area_warning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AOI:
        """Deserialise from a Durable Functions dict payload.

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

        bbox_raw = data.get("bbox", [0.0, 0.0, 0.0, 0.0])
        if not isinstance(bbox_raw, list):
            msg = f"bbox must be a list, got {type(bbox_raw).__name__}"
            raise TypeError(msg)

        buffered_bbox_raw = data.get("buffered_bbox", [0.0, 0.0, 0.0, 0.0])
        if not isinstance(buffered_bbox_raw, list):
            msg = f"buffered_bbox must be a list, got {type(buffered_bbox_raw).__name__}"
            raise TypeError(msg)

        centroid_raw = data.get("centroid", [0.0, 0.0])
        if not isinstance(centroid_raw, list):
            msg = f"centroid must be a list, got {type(centroid_raw).__name__}"
            raise TypeError(msg)

        metadata_raw = data.get("metadata", {})
        if not isinstance(metadata_raw, dict):
            msg = f"metadata must be a dict, got {type(metadata_raw).__name__}"
            raise TypeError(msg)

        return cls(
            feature_name=str(data.get("feature_name", "")),
            source_file=str(data.get("source_file", "")),
            feature_index=int(data.get("feature_index", 0)),  # type: ignore[arg-type]
            exterior_coords=exterior,
            interior_coords=interior,
            bbox=tuple(bbox_raw),  # type: ignore[arg-type]
            buffered_bbox=tuple(buffered_bbox_raw),  # type: ignore[arg-type]
            area_ha=float(data.get("area_ha", 0.0)),  # type: ignore[arg-type]
            centroid=tuple(centroid_raw),  # type: ignore[arg-type]
            buffer_m=float(data.get("buffer_m", 100.0)),  # type: ignore[arg-type]
            crs=str(data.get("crs", "EPSG:4326")),
            metadata={str(k): str(v) for k, v in metadata_raw.items()},
            area_warning=str(data.get("area_warning", "")),
        )

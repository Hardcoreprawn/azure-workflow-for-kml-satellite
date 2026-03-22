"""AOI (Area of Interest) domain model (§2.2).

A feature after geometric processing — includes bounding box, area, centroid.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from treesight.constants import DEFAULT_AOI_BUFFER_M


class AOI(BaseModel):
    """A processed polygon feature with computed geometric properties.

    Attributes:
        feature_name: Source feature name.
        source_file: Source KML filename.
        feature_index: Zero-based feature index.
        exterior_coords: Exterior ring ``[lon, lat]`` pairs.
        interior_coords: Interior rings (holes).
        bbox: Tight bounding box ``[min_lon, min_lat, max_lon, max_lat]``.
        buffered_bbox: Bounding box expanded by ``buffer_m`` metres.
        area_ha: Geodesic polygon area in hectares.
        perimeter_km: Geodesic polygon perimeter in kilometres.
        centroid: Polygon centroid ``[lon, lat]``.
        buffer_m: Buffer distance applied in metres (default 100, range 50–200).
        crs: Always ``EPSG:4326``.
        metadata: Preserved KML metadata.
        area_warning: Non-empty if area exceeds reasonableness threshold.
    """

    feature_name: str
    source_file: str = ""
    feature_index: int = 0
    exterior_coords: list[list[float]] = Field(default_factory=lambda: [])
    interior_coords: list[list[list[float]]] = Field(default_factory=lambda: [])
    bbox: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    buffered_bbox: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    area_ha: float = 0.0
    perimeter_km: float = 0.0
    centroid: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    buffer_m: float = DEFAULT_AOI_BUFFER_M
    crs: str = "EPSG:4326"
    metadata: dict[str, str] = Field(default_factory=dict)
    area_warning: str = ""

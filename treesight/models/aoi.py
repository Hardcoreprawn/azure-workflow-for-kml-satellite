"""AOI (Area of Interest) domain model (§2.2).

A feature after geometric processing — includes bounding box, area, centroid.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

from treesight.constants import DEFAULT_AOI_BUFFER_M
from treesight.models.geometry import PolygonGeometry


class AOI(BaseModel):
    """A processed polygon feature with computed geometric properties.

    Attributes:
        feature_name: Source feature name.
        source_file: Source KML filename.
        feature_index: Zero-based feature index.
        geometry: Polygon or MultiPolygon with explicitly associated holes.
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
    geometry: PolygonGeometry
    bbox: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    buffered_bbox: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    area_ha: float = 0.0
    perimeter_km: float = 0.0
    centroid: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    buffer_m: float = DEFAULT_AOI_BUFFER_M
    metadata: dict[str, str] = Field(default_factory=dict)
    area_warning: str = ""

    @computed_field  # type: ignore[prop-decorator]  # Pydantic computed_field wraps @property.
    @property
    def crs(self) -> str:
        """Coordinate reference system of the source geometry."""
        return self.geometry.crs

    @computed_field  # type: ignore[prop-decorator]  # Pydantic computed_field wraps @property.
    @property
    def dedup_key(self) -> str:
        """Deterministic key for same-named AOIs in a source file.

        Uniqueness assumes ingestion-populated ``source_file`` + ``feature_index``.
        """
        source = self.source_file or "<unspecified>"
        return f"{source}:{self.feature_index}"

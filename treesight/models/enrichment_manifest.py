"""Pydantic contract models for enrichment manifests (#1447)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ENRICHMENT_MANIFEST_V2_SCHEMA = "enrichment-manifest/v2"


class CenterPoint(BaseModel):
    """AOI center point in latitude/longitude order for display and enrichments."""

    lat: float
    lon: float

    model_config = ConfigDict(extra="allow")


class RunSummary(BaseModel):
    """Run-level enrichment summary, not canonical parcel evidence."""

    aoi_count: int = 0
    multi_region: bool = False
    frame_plan: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class PerAoiEnrichment(BaseModel):
    """Canonical enrichment evidence for one AOI within a run."""

    aoi_index: int
    name: str
    area_ha: float
    coords: list[list[float]]
    bbox: list[Any]
    center: CenterPoint
    source_geometry_type: str | None = None
    plot_area_ha: float | None = None
    frame_plan: list[dict[str, Any]] = Field(default_factory=list)
    weather_daily: list[dict[str, Any]] = Field(default_factory=list)
    ndvi_stats: list[dict[str, Any] | None] = Field(default_factory=list)
    ndvi_raster_paths: list[str | None] = Field(default_factory=list)
    change_detection: dict[str, Any] | None = None
    eudr: dict[str, Any] | None = None
    errors: list[Any] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class EnrichmentManifestV2(BaseModel):
    """Boundary contract for new enrichment manifest writes."""

    schema_version: Literal["enrichment-manifest/v2"]
    run: dict[str, Any] = Field(default_factory=dict)
    summary: RunSummary | None = None
    per_aoi_enrichment: list[PerAoiEnrichment] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")

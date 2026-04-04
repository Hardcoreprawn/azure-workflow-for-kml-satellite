"""API request/response contracts for the temporal catalogue.

These schemas define the public API surface.  They are intentionally
decoupled from the Cosmos data model (``models.py``) so the storage
representation can evolve without breaking clients.

Convention:
- ``*Response`` — outbound (serialised to JSON in HTTP responses)
- ``*Params``   — inbound (parsed from query strings / request bodies)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------


class CatalogueQueryParams(BaseModel):
    """Parsed + validated query string for ``GET /api/catalogue``."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    aoi_name: str | None = None
    status: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    provider: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10_000)
    sort: str = "desc"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CatalogueEntryResponse(BaseModel):
    """A single catalogue entry as returned by the API.

    Field names use camelCase to match the existing API convention
    (e.g. ``submittedAt``, ``aoiName``).  Pydantic's alias generator
    handles the conversion; use ``model_dump_json(by_alias=True)``.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    id: str
    run_id: str
    aoi_name: str
    source_file: str = ""
    provider: str = ""

    # Geometry
    centroid: list[float] = Field(default_factory=list)
    bbox: list[float] = Field(default_factory=list)
    area_ha: float = 0.0

    # Temporal
    acquired_at: str | None = None
    submitted_at: str | None = None

    # Quality
    cloud_cover_pct: float | None = None
    spatial_resolution_m: float | None = None
    collection: str = ""

    # Results
    status: str = "pending"
    ndvi_mean: float | None = None
    ndvi_min: float | None = None
    ndvi_max: float | None = None
    change_loss_pct: float | None = None
    change_gain_pct: float | None = None
    change_mean_delta: float | None = None

    # Artifacts
    imagery_blob_path: str = ""
    metadata_blob_path: str = ""
    enrichment_manifest_path: str = ""

    # Housekeeping
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_model(cls, entry: Any) -> CatalogueEntryResponse:
        """Convert a ``CatalogueEntry`` data model to an API response.

        This is the single mapping point between storage and API layers.
        """
        return cls(
            id=entry.id,
            run_id=entry.run_id,
            aoi_name=entry.aoi_name,
            source_file=entry.source_file,
            provider=entry.provider,
            centroid=entry.centroid,
            bbox=entry.bbox,
            area_ha=entry.area_ha,
            acquired_at=entry.acquired_at.isoformat() if entry.acquired_at else None,
            submitted_at=entry.submitted_at.isoformat() if entry.submitted_at else None,
            cloud_cover_pct=entry.cloud_cover_pct,
            spatial_resolution_m=entry.spatial_resolution_m,
            collection=entry.collection,
            status=entry.status,
            ndvi_mean=entry.ndvi_mean,
            ndvi_min=entry.ndvi_min,
            ndvi_max=entry.ndvi_max,
            change_loss_pct=entry.change_loss_pct,
            change_gain_pct=entry.change_gain_pct,
            change_mean_delta=entry.change_mean_delta,
            imagery_blob_path=entry.imagery_blob_path,
            metadata_blob_path=entry.metadata_blob_path,
            enrichment_manifest_path=entry.enrichment_manifest_path,
            created_at=entry.created_at.isoformat() if entry.created_at else None,
            updated_at=entry.updated_at.isoformat() if entry.updated_at else None,
        )


class CatalogueListResponse(BaseModel):
    """Paginated list of catalogue entries."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    entries: list[CatalogueEntryResponse]
    total: int
    offset: int
    limit: int
    has_more: bool

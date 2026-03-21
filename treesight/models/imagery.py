"""Imagery-related models (§2.4, §2.5).

Search criteria and result types for satellite imagery providers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from treesight.constants import (
    DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT,
    DEFAULT_MAX_OFF_NADIR_DEG,
    MAX_OFF_NADIR_DEG_LIMIT,
    MIN_RESOLUTION_M,
)


class ImageryFilters(BaseModel):
    """Search criteria for satellite imagery (§2.4).

    Attributes:
        max_cloud_cover_pct: Maximum cloud cover percentage (0–100).
        max_off_nadir_deg: Maximum off-nadir angle in degrees (0–45).
        min_resolution_m: Minimum ground sample distance in metres (≥ 0.01).
        max_resolution_m: Maximum ground sample distance in metres (≥ min_resolution_m).
        date_start: Start of date range filter.
        date_end: End of date range filter.
        collections: Provider-specific collection IDs.
    """

    max_cloud_cover_pct: float = Field(
        default=DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT, ge=0.0, le=100.0
    )
    max_off_nadir_deg: float = Field(
        default=DEFAULT_MAX_OFF_NADIR_DEG, ge=0.0, le=MAX_OFF_NADIR_DEG_LIMIT
    )
    min_resolution_m: float = Field(default=MIN_RESOLUTION_M, ge=MIN_RESOLUTION_M)
    max_resolution_m: float = Field(default=0.5, ge=MIN_RESOLUTION_M)
    date_start: datetime | None = None
    date_end: datetime | None = None
    collections: list[str] = Field(default_factory=list)

    @field_validator("date_end")
    @classmethod
    def date_end_after_start(cls, v: datetime | None, info: Any) -> datetime | None:
        """Validate that date_end ≥ date_start when both are set."""
        start = info.data.get("date_start")
        if v is not None and start is not None and v < start:
            msg = "date_end must be >= date_start"
            raise ValueError(msg)
        return v

    @field_validator("max_resolution_m")
    @classmethod
    def max_gte_min_resolution(cls, v: float, info: Any) -> float:
        """Validate that max_resolution_m ≥ min_resolution_m."""
        min_res = info.data.get("min_resolution_m", MIN_RESOLUTION_M)
        if v < min_res:
            msg = "max_resolution_m must be >= min_resolution_m"
            raise ValueError(msg)
        return v


class SearchResult(BaseModel):
    """A scene returned by a provider search (§2.5).

    Attributes:
        scene_id: Provider-specific scene identifier (non-empty).
        provider: Provider name (non-empty).
        acquisition_date: When the scene was captured.
        cloud_cover_pct: Cloud cover percentage (0–100).
        spatial_resolution_m: Ground sample distance in metres (≥ 0.01).
        off_nadir_deg: Off-nadir angle in degrees (≥ 0).
        crs: Scene CRS (e.g. ``EPSG:32637``).
        bbox: Scene extent ``[min_lon, min_lat, max_lon, max_lat]``.
        asset_url: Direct download URL (if available).
        extra: Provider-specific metadata.
    """

    scene_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    acquisition_date: datetime
    cloud_cover_pct: float = Field(ge=0.0, le=100.0)
    spatial_resolution_m: float = Field(ge=MIN_RESOLUTION_M)
    off_nadir_deg: float = Field(ge=0.0)
    crs: str
    bbox: list[float]
    asset_url: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)

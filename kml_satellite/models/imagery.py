"""Typed models for the imagery provider adapter layer.

Defines the data structures exchanged between the orchestrator and
provider adapters:

- ``ImageryFilters``: Search criteria (date range, cloud cover, resolution, etc.)
- ``SearchResult``: A single scene/asset returned by a provider search
- ``OrderId``: Opaque order identifier returned by a provider
- ``OrderStatus``: Status of an asynchronous imagery order
- ``BlobReference``: Pointer to imagery stored in Azure Blob Storage
- ``ProviderConfig``: Configuration for a specific imagery provider

Design notes:
- All models are frozen dataclasses for immutability (PID 7.4.5).
- Explicit units on every numeric field (PID 7.4.5).
- No magic strings — status values are an ``OrderState`` enum.

References:
    PID FR-3.1  (provider-agnostic abstraction)
    PID FR-3.7  (API authentication via Key Vault)
    PID FR-3.13 (configurable filters: cloud cover, date range, off-nadir)
    PID Section 7.3  (Provider Adapter Layer)
    PID Section 7.4.5 (Explicit Over Implicit)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kml_satellite.core.exceptions import PipelineError

if TYPE_CHECKING:
    from datetime import datetime


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ModelValidationError(ValueError, PipelineError):
    """Raised when a domain model is constructed with invalid field values.

    Attributes:
        model: Name of the model class that failed validation.
        field_name: The field that violated the invariant.
        value: The invalid value.
    """

    default_stage = "model_validation"
    default_code = "MODEL_VALIDATION_FAILED"

    def __init__(self, model: str, field_name: str, value: object, message: str) -> None:
        self.model = model
        self.field_name = field_name
        self.value = value
        formatted = f"{model}.{field_name}={value!r}: {message}"
        PipelineError.__init__(self, formatted)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderState(enum.Enum):
    """Lifecycle state of an imagery order.

    Values:
        PENDING:   Order submitted, fulfilment in progress.
        READY:     Imagery is available for download.
        FAILED:    Provider permanently rejected the order.
        CANCELLED: Order was cancelled (by timeout or user).
    """

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Search models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImageryFilters:
    """Criteria for searching a provider's imagery archive.

    Resolution is bounded by a range:
    ``min_resolution_m <= resolution <= max_resolution_m``.
    All other numeric thresholds are *maximum* values — the provider
    should return only scenes that fall at or below these limits.

    Attributes:
        max_cloud_cover_pct: Maximum acceptable cloud cover (0-100).
        max_off_nadir_deg: Maximum acceptable off-nadir angle in degrees (0-45).
        min_resolution_m: Minimum spatial resolution in metres (inclusive lower bound).
        max_resolution_m: Maximum spatial resolution in metres (inclusive upper bound).
        date_start: Earliest acceptable acquisition date (inclusive).
        date_end: Latest acceptable acquisition date (inclusive).
        collections: Provider-specific collection identifiers to search.
    """

    max_cloud_cover_pct: float = 20.0
    max_off_nadir_deg: float = 30.0
    min_resolution_m: float = 0.0
    max_resolution_m: float = 50.0
    date_start: datetime | None = None
    date_end: datetime | None = None
    collections: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _check_range("ImageryFilters", "max_cloud_cover_pct", self.max_cloud_cover_pct, 0, 100)
        _check_range("ImageryFilters", "max_off_nadir_deg", self.max_off_nadir_deg, 0, 90)
        _check_min("ImageryFilters", "min_resolution_m", self.min_resolution_m, 0)
        _check_min("ImageryFilters", "max_resolution_m", self.max_resolution_m, 0)
        if self.min_resolution_m > self.max_resolution_m:
            raise ModelValidationError(
                "ImageryFilters",
                "min_resolution_m",
                self.min_resolution_m,
                f"must be <= max_resolution_m ({self.max_resolution_m})",
            )
        if (
            self.date_start is not None
            and self.date_end is not None
            and self.date_start > self.date_end
        ):
            raise ModelValidationError(
                "ImageryFilters",
                "date_start",
                self.date_start,
                f"must be <= date_end ({self.date_end})",
            )


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A single scene or asset returned by a provider search.

    Attributes:
        scene_id: Provider-specific unique identifier for the scene.
        provider: Name of the imagery provider (e.g. ``"planetary_computer"``).
        acquisition_date: Date/time the scene was captured.
        cloud_cover_pct: Cloud cover percentage for the scene (0-100).
        spatial_resolution_m: Ground sample distance in metres.
        off_nadir_deg: Off-nadir angle in degrees (0 = looking straight down).
        crs: Coordinate reference system of the scene (e.g. ``"EPSG:32637"``).
        bbox: Scene bounding box as ``(min_lon, min_lat, max_lon, max_lat)``.
        asset_url: Direct URL for download (if immediately available).
        extra: Provider-specific additional metadata.
    """

    scene_id: str
    provider: str
    acquisition_date: datetime
    cloud_cover_pct: float = 0.0
    spatial_resolution_m: float = 0.0
    off_nadir_deg: float = 0.0
    crs: str = "EPSG:4326"
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    asset_url: str = ""
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_non_empty("SearchResult", "scene_id", self.scene_id)
        _check_non_empty("SearchResult", "provider", self.provider)
        _check_range("SearchResult", "cloud_cover_pct", self.cloud_cover_pct, 0, 100)
        _check_min("SearchResult", "spatial_resolution_m", self.spatial_resolution_m, 0)
        _check_min("SearchResult", "off_nadir_deg", self.off_nadir_deg, 0)


# ---------------------------------------------------------------------------
# Order models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderId:
    """Opaque identifier for a submitted imagery order.

    Attributes:
        provider: Name of the imagery provider.
        order_id: Provider-specific order identifier.
        scene_id: The scene that was ordered.
    """

    provider: str
    order_id: str
    scene_id: str


@dataclass(frozen=True, slots=True)
class OrderStatus:
    """Current status of an imagery order.

    Attributes:
        order_id: The order being checked.
        state: Current lifecycle state.
        message: Human-readable status message from the provider.
        progress_pct: Estimated completion percentage (0-100), if available.
        download_url: URL to download imagery (populated when ``state == READY``).
        updated_at: Timestamp of the last status update.
    """

    order_id: str
    state: OrderState
    message: str = ""
    progress_pct: float = 0.0
    download_url: str = ""
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _check_non_empty("OrderStatus", "order_id", self.order_id)
        _check_range("OrderStatus", "progress_pct", self.progress_pct, 0, 100)


@dataclass(frozen=True, slots=True)
class BlobReference:
    """Pointer to imagery stored in Azure Blob Storage.

    Attributes:
        container: Blob container name.
        blob_path: Full path within the container.
        size_bytes: Size of the stored blob in bytes.
        content_type: MIME content type (e.g. ``"image/tiff"``).
    """

    container: str
    blob_path: str
    size_bytes: int = 0
    content_type: str = "image/tiff"

    def __post_init__(self) -> None:
        _check_non_empty("BlobReference", "container", self.container)
        _check_non_empty("BlobReference", "blob_path", self.blob_path)
        _check_min("BlobReference", "size_bytes", self.size_bytes, 0)


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Configuration for a specific imagery provider.

    Loaded from environment variables or Azure App Configuration.

    Attributes:
        name: Provider identifier (must match the adapter registry key).
        api_base_url: Base URL for the provider's API.
        auth_mechanism: How to authenticate (``"none"``, ``"api_key"``, ``"oauth2"``).
        keyvault_secret_name: Key Vault secret name for API credentials (empty if no auth).
        extra_params: Provider-specific configuration parameters.
    """

    name: str
    api_base_url: str = ""
    auth_mechanism: str = "none"
    keyvault_secret_name: str = ""
    extra_params: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_non_empty("ProviderConfig", "name", self.name)


# ---------------------------------------------------------------------------
# Validation helpers (module-private)
# ---------------------------------------------------------------------------


def _check_range(model: str, field_name: str, value: float, lo: float, hi: float) -> None:
    """Raise `ModelValidationError` if *value* falls outside [lo, hi]."""
    if value < lo or value > hi:
        raise ModelValidationError(model, field_name, value, f"must be between {lo} and {hi}")


def _check_min(model: str, field_name: str, value: float | int, lo: float | int) -> None:
    """Raise `ModelValidationError` if *value* is below *lo*."""
    if value < lo:
        raise ModelValidationError(model, field_name, value, f"must be >= {lo}")


def _check_non_empty(model: str, field_name: str, value: str) -> None:
    """Raise `ModelValidationError` if *value* is empty or blank."""
    if not value or not value.strip():
        raise ModelValidationError(model, field_name, value, "must not be empty")

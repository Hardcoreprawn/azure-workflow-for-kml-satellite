"""Canonical payload contracts for activity/orchestrator boundaries.

Every activity input and output is defined here as a ``TypedDict``.  This
module is the single source of truth for field names — any rename is a
compile-time error caught by pyright, and drift-detection tests verify
runtime compliance.

Design notes:
- ``TypedDict`` was chosen over ``dataclass`` because Durable Functions
  serialises everything to JSON dicts.  TypedDicts need no conversion.
- Input contracts use ``total=False`` for optional override fields.
- Output contracts use ``total=True`` so missing keys are flagged.

References:
    PID 7.4.5  (Explicit over Implicit — typed boundaries)
    Issue #51  (Canonical payload contract module)
"""

from __future__ import annotations

from typing import TypedDict

# ---------------------------------------------------------------------------
# Orchestration input (function_app → orchestrator)
# ---------------------------------------------------------------------------


class OrchestrationInput(TypedDict):
    """Payload produced by ``BlobEvent.to_dict()`` and consumed by the orchestrator."""

    blob_url: str
    container_name: str
    blob_name: str
    content_length: int
    content_type: str
    event_time: str
    correlation_id: str
    tenant_id: str
    output_container: str


class OrchestrationOverrides(TypedDict, total=False):
    """Optional overrides injected into the orchestration input."""

    provider_name: str
    provider_config: dict[str, str] | None
    imagery_filters: dict[str, object] | None
    poll_interval_seconds: int
    poll_timeout_seconds: int
    max_retries: int
    retry_base_seconds: int
    enable_clipping: bool
    enable_reprojection: bool
    target_crs: str


# ---------------------------------------------------------------------------
# parse_kml  (input = OrchestrationInput, output = list[FeaturePayload])
# ---------------------------------------------------------------------------


class FeaturePayload(TypedDict):
    """Serialised ``Feature`` — output of ``parse_kml``, input to ``prepare_aoi``."""

    name: str
    description: str
    exterior_coords: list[list[float]]
    interior_coords: list[list[list[float]]]
    crs: str
    metadata: dict[str, str]
    source_file: str
    feature_index: int


# ---------------------------------------------------------------------------
# prepare_aoi  (input = FeaturePayload, output = AOIPayload)
# ---------------------------------------------------------------------------


class AOIPayload(TypedDict):
    """Serialised ``AOI`` — output of ``prepare_aoi``, used downstream."""

    feature_name: str
    source_file: str
    feature_index: int
    exterior_coords: list[list[float]]
    interior_coords: list[list[list[float]]]
    bbox: list[float]
    buffered_bbox: list[float]
    area_ha: float
    centroid: list[float]
    buffer_m: float
    crs: str
    metadata: dict[str, str]
    area_warning: str


# ---------------------------------------------------------------------------
# acquire_imagery
# ---------------------------------------------------------------------------


class AcquireImageryInput(TypedDict):
    """Input to ``acquire_imagery`` activity."""

    aoi: AOIPayload
    provider_name: str
    provider_config: dict[str, str] | None
    imagery_filters: dict[str, object] | None


class AcquisitionResult(TypedDict):
    """Output of ``acquire_imagery`` activity."""

    order_id: str
    scene_id: str
    provider: str
    cloud_cover_pct: float
    acquisition_date: str
    spatial_resolution_m: float
    asset_url: str
    aoi_feature_name: str


# ---------------------------------------------------------------------------
# poll_order
# ---------------------------------------------------------------------------


class PollOrderInput(TypedDict):
    """Input to ``poll_order`` activity."""

    order_id: str
    provider: str


class PollResult(TypedDict):
    """Output of ``poll_order`` activity."""

    order_id: str
    state: str
    message: str
    progress_pct: float
    is_terminal: bool


# ---------------------------------------------------------------------------
# Imagery outcome (produced by orchestrator _poll_until_ready)
# ---------------------------------------------------------------------------


class ImageryOutcome(TypedDict):
    """Result of the polling phase — passed to download."""

    state: str
    order_id: str
    scene_id: str
    provider: str
    aoi_feature_name: str
    poll_count: int
    elapsed_seconds: float
    error: str


# ---------------------------------------------------------------------------
# download_imagery
# ---------------------------------------------------------------------------


class DownloadImageryInput(TypedDict):
    """Input to ``download_imagery`` activity."""

    imagery_outcome: ImageryOutcome
    provider_name: str
    provider_config: dict[str, str] | None
    project_name: str
    timestamp: str
    output_container: str


class DownloadResult(TypedDict):
    """Output of ``download_imagery`` activity."""

    order_id: str
    scene_id: str
    provider: str
    aoi_feature_name: str
    blob_path: str
    adapter_blob_path: str
    container: str
    size_bytes: int
    content_type: str
    download_duration_seconds: float
    retry_count: int


# ---------------------------------------------------------------------------
# post_process_imagery
# ---------------------------------------------------------------------------


class PostProcessInput(TypedDict):
    """Input to ``post_process_imagery`` activity."""

    download_result: DownloadResult
    aoi: AOIPayload
    project_name: str
    timestamp: str
    target_crs: str
    enable_clipping: bool
    enable_reprojection: bool
    output_container: str


class PostProcessResult(TypedDict):
    """Output of ``post_process_imagery`` activity."""

    order_id: str
    source_blob_path: str
    clipped_blob_path: str
    container: str
    clipped: bool
    reprojected: bool
    source_crs: str
    target_crs: str
    source_size_bytes: int
    output_size_bytes: int
    processing_duration_seconds: float
    clip_error: str


# ---------------------------------------------------------------------------
# write_metadata
# ---------------------------------------------------------------------------


class WriteMetadataInput(TypedDict):
    """Input to ``write_metadata`` activity."""

    aoi: AOIPayload
    processing_id: str
    timestamp: str
    tenant_id: str


class MetadataResult(TypedDict):
    """Output of ``write_metadata`` activity."""

    metadata: dict[str, object]
    metadata_path: str
    kml_archive_path: str


# ---------------------------------------------------------------------------
# Orchestration final result
# ---------------------------------------------------------------------------


class OrchestrationResult(TypedDict):
    """Final output of the KML processing orchestrator."""

    status: str
    instance_id: str
    blob_name: str
    blob_url: str
    feature_count: int
    aoi_count: int
    metadata_count: int
    imagery_ready: int
    imagery_failed: int
    downloads_completed: int
    post_process_completed: int
    post_process_clipped: int
    post_process_reprojected: int
    imagery_outcomes: list[ImageryOutcome]
    download_results: list[DownloadResult]
    post_process_results: list[PostProcessResult]
    message: str

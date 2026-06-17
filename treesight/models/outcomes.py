"""Pipeline outcome models (§3.1–§3.4).

Result types for each pipeline phase and the final summary.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

# Poll lifecycle values emitted by providers and normalized pipeline outcomes.
ImageryOutcomeState = Literal[
    "active",
    "pending",
    "processing",
    "ready",
    "completed",
    "failed",
    "error",
    "cancelled",
    "acquisition_timeout",
]
# Terminal state for download and post-process transfers.
TransferState = Literal["completed", "failed"]
# Final orchestrator summary status.
PipelineStatus = Literal["pending", "completed", "partial_imagery"]


class MetadataResult(BaseModel):
    """Result of writing AOI metadata to blob storage."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    metadata_path: str = ""
    kml_archive_path: str = ""


class IngestionResult(BaseModel):
    """Phase 1 result — KML parsing and AOI preparation."""

    feature_count: int = 0
    offloaded: bool = False
    aois: list[dict[str, Any]] = Field(default_factory=list)
    aoi_count: int = 0
    metadata_results: list[MetadataResult] = Field(default_factory=list)
    metadata_count: int = 0


class ImageryOutcome(BaseModel):
    """Result of imagery acquisition for a single AOI.

    Attributes:
        state: One of ``ready``, ``failed``, ``cancelled``, ``acquisition_timeout``.
        order_id: Provider order identifier.
        scene_id: Provider scene identifier.
        provider: Provider name.
        aoi_feature_name: Name of the AOI this outcome relates to.
        poll_count: Number of poll attempts.
        elapsed_seconds: Total time spent polling.
        error: Error message (empty on success).
    """

    state: ImageryOutcomeState = "pending"
    order_id: str = ""
    scene_id: str = ""
    provider: str = ""
    aoi_feature_name: str = ""
    poll_count: int = 0
    elapsed_seconds: float = 0.0
    error: str = ""
    cloud_cover_pct: float = 0.0
    acquisition_date: str = ""
    spatial_resolution_m: float = 0.0
    asset_url: str = ""
    role: str = ""
    collection: str = ""


class AcquisitionResult(BaseModel):
    """Phase 2 result — imagery search, order, and polling."""

    imagery_outcomes: list[ImageryOutcome] = Field(default_factory=list)
    ready_count: int = 0
    failed_count: int = 0


class DownloadResult(BaseModel):
    """Result of downloading a single imagery asset (§9.2).

    All 11 fields are present on success. On failure, ``state`` is ``"failed"``
    and ``error`` contains a human-readable message.
    """

    order_id: str = ""
    scene_id: str = ""
    provider: str = ""
    aoi_feature_name: str = ""
    blob_path: str = ""
    adapter_blob_path: str = ""
    container: str = ""
    size_bytes: int = 0
    content_type: str = ""
    download_duration_seconds: float = 0.0
    retry_count: int = 0
    state: TransferState = "completed"
    error: str = ""


class PostProcessResult(BaseModel):
    """Result of post-processing a downloaded GeoTIFF (§9.3)."""

    order_id: str = ""
    source_blob_path: str = ""
    clipped_blob_path: str = ""
    container: str = ""
    clipped: bool = False
    reprojected: bool = False
    source_crs: str = ""
    target_crs: str = ""
    source_size_bytes: int = 0
    output_size_bytes: int = 0
    processing_duration_seconds: float = 0.0
    state: TransferState = "completed"
    error: str = ""
    clip_error: str = ""


class FulfillmentResult(BaseModel):
    """Phase 3 result — download and post-processing."""

    download_results: list[DownloadResult] = Field(default_factory=list)
    downloads_completed: int = 0
    downloads_succeeded: int = 0
    downloads_failed: int = 0
    post_process_results: list[PostProcessResult] = Field(default_factory=list)
    pp_completed: int = 0
    pp_clipped: int = 0
    pp_reprojected: int = 0
    pp_failed: int = 0


class AoiSummary(BaseModel):
    """Per-AOI breakdown aggregated from pipeline phase results."""

    feature_name: str = ""
    imagery_ready: int = 0
    imagery_failed: int = 0
    downloads_succeeded: int = 0
    downloads_failed: int = 0
    post_process_completed: int = 0
    post_process_failed: int = 0


class PipelineSummaryCounts(BaseModel):
    """Headline counts and status for completed orchestration output.

    Status is ``pending`` before ``compute_status()`` runs, then ``completed`` when all
    imagery succeeded, otherwise ``partial_imagery``.
    """

    status: PipelineStatus = "pending"
    instance_id: str = ""
    blob_name: str = ""
    blob_url: str = ""
    feature_count: int = 0
    aoi_count: int = 0
    metadata_count: int = 0
    imagery_ready: int = 0
    imagery_failed: int = 0
    downloads_completed: int = 0
    downloads_succeeded: int = 0
    downloads_failed: int = 0
    post_process_completed: int = 0
    post_process_clipped: int = 0
    post_process_reprojected: int = 0
    post_process_failed: int = 0
    message: str = ""


class PipelineSummary(PipelineSummaryCounts):
    """Final pipeline output aggregating all three phases (§3.4)."""

    metadata_results: list[MetadataResult] = Field(default_factory=list)
    imagery_outcomes: list[ImageryOutcome] = Field(default_factory=list)
    download_results: list[DownloadResult] = Field(default_factory=list)
    post_process_results: list[PostProcessResult] = Field(default_factory=list)
    per_aoi_summaries: list[AoiSummary] = Field(default_factory=list)

    def compute_status(self) -> None:
        """Compute ``status`` and ``message`` from phase results (§3.4)."""
        all_good = (
            self.imagery_failed == 0
            and self.downloads_failed == 0
            and self.downloads_succeeded == self.imagery_ready
            and self.post_process_failed == 0
        )
        self.status = "completed" if all_good else "partial_imagery"
        self.message = (
            f"Parsed {self.feature_count} feature(s), "
            f"prepared {self.aoi_count} AOI(s), "
            f"wrote {self.metadata_count} metadata record(s), "
            f"imagery ready={self.imagery_ready} failed={self.imagery_failed}, "
            f"downloaded={self.downloads_completed}, "
            f"clipped={self.post_process_clipped} "
            f"reprojected={self.post_process_reprojected}."
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def artifacts(self) -> dict[str, list[str]]:
        """Aggregate artifact paths for the diagnostics endpoint (§4.3)."""
        metadata_paths = [r.metadata_path for r in self.metadata_results if r.metadata_path]
        raw_paths = [r.blob_path for r in self.download_results if r.blob_path]
        clipped_paths = [
            r.clipped_blob_path
            for r in self.post_process_results
            if r.clipped_blob_path
        ]
        return {
            "metadataPaths": metadata_paths,
            "rawImageryPaths": raw_paths,
            "clippedImageryPaths": clipped_paths,
        }

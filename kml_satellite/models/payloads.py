"""Typed payload schemas for Durable Functions activity contracts (Issue #43).

Every activity in the pipeline receives and returns a JSON-serialisable
dict.  These ``TypedDict`` definitions make the contracts explicit so
that pyright catches key mismatches at analysis time and
``validate_payload`` catches them at runtime.

Usage::

    from kml_satellite.models.payloads import ParseKmlInput, validate_payload

    def parse_kml_activity(raw: dict) -> ...:
        validate_payload(raw, ParseKmlInput, activity="parse_kml")
        # raw is now known to contain all required keys
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from kml_satellite.core.exceptions import ContractError

# ---------------------------------------------------------------------------
# Parse KML (Phase 1)
# ---------------------------------------------------------------------------


class ParseKmlInput(TypedDict):
    """Orchestrator → ``parse_kml`` activity."""

    container_name: str
    blob_name: str
    correlation_id: NotRequired[str]


# Output is ``list[FeatureDict]`` — see Feature.to_dict().

# ---------------------------------------------------------------------------
# Prepare AOI (Phase 2)
# ---------------------------------------------------------------------------

# Input is a serialised Feature dict — see Feature.to_dict().
# Output is a serialised AOI dict — see AOI.to_dict().

# ---------------------------------------------------------------------------
# Write Metadata (Phase 3)
# ---------------------------------------------------------------------------


class WriteMetadataInput(TypedDict):
    """Orchestrator → ``write_metadata`` activity."""

    aoi: dict[str, Any]
    processing_id: str
    timestamp: str


class WriteMetadataOutput(TypedDict):
    """``write_metadata`` activity → orchestrator."""

    metadata: dict[str, Any]
    metadata_path: str
    kml_archive_path: str


# ---------------------------------------------------------------------------
# Acquire Imagery (Phase 4)
# ---------------------------------------------------------------------------


class AcquireImageryInput(TypedDict):
    """Orchestrator → ``acquire_imagery`` activity."""

    aoi: dict[str, Any]
    provider_name: NotRequired[str]
    provider_config: NotRequired[dict[str, Any] | None]
    imagery_filters: NotRequired[dict[str, Any] | None]


class AcquireImageryOutput(TypedDict):
    """``acquire_imagery`` activity → orchestrator."""

    order_id: str
    scene_id: str
    provider: str
    cloud_cover_pct: float
    acquisition_date: str
    spatial_resolution_m: float
    asset_url: str
    aoi_feature_name: str


# ---------------------------------------------------------------------------
# Poll Order (Phase 5)
# ---------------------------------------------------------------------------


class PollOrderInput(TypedDict):
    """Orchestrator → ``poll_order`` activity."""

    order_id: str
    provider: str


class PollOrderOutput(TypedDict):
    """``poll_order`` activity → orchestrator."""

    order_id: str
    state: str
    message: str
    progress_pct: float
    is_terminal: bool


# ---------------------------------------------------------------------------
# Download Imagery (Phase 6)
# ---------------------------------------------------------------------------


class DownloadImageryInput(TypedDict):
    """Orchestrator → ``download_imagery`` activity."""

    imagery_outcome: dict[str, Any]
    provider_name: NotRequired[str]
    provider_config: NotRequired[dict[str, Any] | None]
    project_name: NotRequired[str]
    timestamp: NotRequired[str]


class DownloadImageryOutput(TypedDict):
    """``download_imagery`` activity → orchestrator."""

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
# Post-Process Imagery (Phase 7)
# ---------------------------------------------------------------------------


class PostProcessImageryInput(TypedDict):
    """Orchestrator → ``post_process_imagery`` activity."""

    download_result: dict[str, Any]
    aoi: dict[str, Any]
    project_name: NotRequired[str]
    timestamp: NotRequired[str]
    target_crs: NotRequired[str]
    enable_clipping: NotRequired[bool]
    enable_reprojection: NotRequired[bool]


class PostProcessImageryOutput(TypedDict):
    """``post_process_imagery`` activity → orchestrator."""

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
# Required-key registrations (used by validate_payload)
# ---------------------------------------------------------------------------

_REQUIRED_KEYS: dict[type, frozenset[str]] = {
    ParseKmlInput: frozenset({"container_name", "blob_name"}),
    WriteMetadataInput: frozenset({"aoi", "processing_id", "timestamp"}),
    AcquireImageryInput: frozenset({"aoi"}),
    PollOrderInput: frozenset({"order_id", "provider"}),
    DownloadImageryInput: frozenset({"imagery_outcome"}),
    PostProcessImageryInput: frozenset({"download_result", "aoi"}),
}


# ---------------------------------------------------------------------------
# Runtime validation
# ---------------------------------------------------------------------------


def validate_payload(
    raw: dict[str, Any],
    schema: type,
    *,
    activity: str,
) -> None:
    """Validate that *raw* contains the required keys for *schema*.

    Raises:
        ContractError: If required keys are missing from the payload.
    """
    required = _REQUIRED_KEYS.get(schema)
    if required is None:
        return

    missing = required - raw.keys()
    if missing:
        msg = f"{activity}: missing required payload key(s): {', '.join(sorted(missing))}"
        raise ContractError(msg, stage=activity, code="PAYLOAD_MISSING_KEYS")

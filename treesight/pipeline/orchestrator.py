"""Durable Functions orchestrator — three-phase pipeline (§3).

This module defines the orchestration logic. The actual Azure Functions
bindings (triggers, activities) live in blueprints/pipeline.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from treesight.config import config_get_int
from treesight.constants import (
    DEFAULT_DOWNLOAD_BATCH_SIZE,
    DEFAULT_POLL_BATCH_SIZE,
    DEFAULT_POST_PROCESS_BATCH_SIZE,
)
from treesight.log import log_phase
from treesight.models.outcomes import PipelineSummary


def build_pipeline_summary(
    instance_id: str,
    blob_name: str,
    blob_url: str,
    ingestion: dict[str, Any],
    acquisition: dict[str, Any],
    fulfilment: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate phase results into a PipelineSummary."""
    summary = PipelineSummary(
        instance_id=instance_id,
        blob_name=blob_name,
        blob_url=blob_url,
        feature_count=ingestion.get("feature_count", 0),
        aoi_count=ingestion.get("aoi_count", 0),
        metadata_count=ingestion.get("metadata_count", 0),
        metadata_results=ingestion.get("metadata_results", []),
        imagery_ready=acquisition.get("ready_count", 0),
        imagery_failed=acquisition.get("failed_count", 0),
        imagery_outcomes=acquisition.get("imagery_outcomes", []),
        downloads_completed=fulfilment.get("downloads_completed", 0),
        downloads_succeeded=fulfilment.get("downloads_succeeded", 0),
        downloads_failed=fulfilment.get("downloads_failed", 0),
        download_results=fulfilment.get("download_results", []),
        post_process_completed=fulfilment.get("pp_completed", 0),
        post_process_clipped=fulfilment.get("pp_clipped", 0),
        post_process_reprojected=fulfilment.get("pp_reprojected", 0),
        post_process_failed=fulfilment.get("pp_failed", 0),
        post_process_results=fulfilment.get("post_process_results", []),
    )
    summary.compute_status()

    log_phase(
        "pipeline",
        "summary",
        instance=instance_id,
        status=summary.status,
        features=summary.feature_count,
        ready=summary.imagery_ready,
        failed=summary.imagery_failed,
    )

    return summary.model_dump()


def get_batch_config(overrides: dict[str, Any]) -> dict[str, int]:
    """Extract batch configuration from orchestrator input."""
    return {
        "poll_batch_size": config_get_int(
            overrides,
            "poll_batch_size",
            DEFAULT_POLL_BATCH_SIZE,
        ),
        "download_batch_size": config_get_int(
            overrides,
            "download_batch_size",
            DEFAULT_DOWNLOAD_BATCH_SIZE,
        ),
        "post_process_batch_size": config_get_int(
            overrides,
            "post_process_batch_size",
            DEFAULT_POST_PROCESS_BATCH_SIZE,
        ),
    }


def derive_project_context(blob_name: str) -> dict[str, str]:
    """Derive project_name and timestamp from blob name."""
    return {
        "project_name": PurePosixPath(blob_name).stem,
        "timestamp": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
    }

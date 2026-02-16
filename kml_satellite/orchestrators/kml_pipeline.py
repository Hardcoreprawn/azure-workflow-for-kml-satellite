"""Durable Functions orchestrator for the KML processing pipeline.

Receives a ``BlobEvent`` dict from the trigger function and coordinates
the pipeline steps:

1. Parse KML (activity) — extract features
2. Fan-out per polygon — prepare AOI + acquire imagery
3. Fan-in — collect results and write metadata

This module currently implements the **stub** orchestrator per M-1.2.
Activity calls will be wired in subsequent milestones.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

    import azure.durable_functions as df

logger = logging.getLogger("kml_satellite.orchestrators.kml_pipeline")


def orchestrator_function(
    context: df.DurableOrchestrationContext,
) -> Generator[Any, Any, dict[str, object]]:
    """KML processing pipeline orchestrator.

    Args:
        context: Durable Functions orchestration context.

    Returns:
        Dict summarising the orchestration result.

    Input (via ``context.get_input``):
        A ``BlobEvent`` dict with keys: ``blob_url``, ``container_name``,
        ``blob_name``, ``content_length``, ``content_type``, ``event_time``,
        ``correlation_id``.
    """
    blob_event: dict[str, object] = context.get_input() or {}
    instance_id = context.instance_id
    blob_name = blob_event.get("blob_name", "<unknown>")

    if not context.is_replaying:
        logger.info(
            "Orchestrator started | instance=%s | blob=%s | correlation_id=%s",
            instance_id,
            blob_name,
            blob_event.get("correlation_id", ""),
        )

    # -----------------------------------------------------------------------
    # Phase 1: Parse KML (M-1.3)
    # -----------------------------------------------------------------------
    features = yield context.call_activity("parse_kml", blob_event)

    if not context.is_replaying:
        logger.info(
            "KML parsed | instance=%s | features=%d | blob=%s",
            instance_id,
            len(features) if isinstance(features, list) else 0,
            blob_name,
        )

    # -----------------------------------------------------------------------
    # Phase 2: Fan-out per polygon — prepare AOI (M-1.5)
    # -----------------------------------------------------------------------
    aoi_tasks = [context.call_activity("prepare_aoi", f) for f in features]
    aois = yield context.task_all(aoi_tasks)

    if not context.is_replaying:
        aoi_count = len(aois) if isinstance(aois, list) else 0
        logger.info(
            "AOIs prepared | instance=%s | aois=%d | blob=%s",
            instance_id,
            aoi_count,
            blob_name,
        )

    # -----------------------------------------------------------------------
    # Phase 3: Write metadata per AOI (M-1.6)
    # -----------------------------------------------------------------------
    from datetime import UTC, datetime

    timestamp = datetime.now(tz=UTC).isoformat()
    metadata_tasks = [
        context.call_activity(
            "write_metadata",
            {
                "aoi": a,
                "processing_id": instance_id,
                "timestamp": timestamp,
            },
        )
        for a in aois
    ]
    metadata_results = yield context.task_all(metadata_tasks)

    if not context.is_replaying:
        metadata_count = len(metadata_results) if isinstance(metadata_results, list) else 0
        logger.info(
            "Metadata written | instance=%s | records=%d | blob=%s",
            instance_id,
            metadata_count,
            blob_name,
        )

    # -----------------------------------------------------------------------
    # Phase 4: Acquire imagery (M-2.x)
    # -----------------------------------------------------------------------
    # imagery_tasks = [context.call_activity("acquire_imagery", a) for a in aois]
    # imagery_results = yield context.task_all(imagery_tasks)

    # -----------------------------------------------------------------------
    # Result summary
    # -----------------------------------------------------------------------
    feature_count = len(features) if isinstance(features, list) else 0
    aoi_count = len(aois) if isinstance(aois, list) else 0
    metadata_count = len(metadata_results) if isinstance(metadata_results, list) else 0
    result = {
        "status": "metadata_written",
        "instance_id": instance_id,
        "blob_name": blob_name,
        "blob_url": blob_event.get("blob_url", ""),
        "feature_count": feature_count,
        "aoi_count": aoi_count,
        "metadata_count": metadata_count,
        "message": (
            f"Parsed {feature_count} feature(s), "
            f"prepared {aoi_count} AOI(s), "
            f"wrote {metadata_count} metadata record(s) "
            f"— awaiting imagery activities."
        ),
    }

    if not context.is_replaying:
        logger.info(
            "Orchestrator completed | instance=%s | blob=%s | features=%d",
            instance_id,
            blob_name,
            feature_count,
        )

    return result

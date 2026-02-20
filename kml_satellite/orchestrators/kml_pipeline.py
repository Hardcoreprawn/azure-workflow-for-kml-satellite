"""Durable Functions orchestrator for the KML processing pipeline.

Thin coordinator that sequences three bounded phases (Issue #59):

1. **Ingestion** — parse KML, prepare AOIs, write metadata.
2. **Acquisition** — acquire imagery, timer-based polling.
3. **Fulfillment** — download imagery, clip / reproject.

Phase logic lives in ``kml_satellite.orchestrators.phases``.  This module
is responsible only for input extraction, phase sequencing, and final
result assembly.

References:
    PID FR-5.3  (Durable Functions for long-running workflows)
    PID Section 7.2 (Fan-Out / Fan-In orchestration pattern)
    Issue #59   (Decompose pipeline orchestration)
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from kml_satellite.orchestrators.phases import (
    DEFAULT_DOWNLOAD_BATCH_SIZE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_POST_PROCESS_BATCH_SIZE,
    DEFAULT_RETRY_BASE_SECONDS,
    _poll_until_ready,
    build_pipeline_summary,
    run_acquisition_phase,
    run_fulfillment_phase,
    run_ingestion_phase,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    import azure.durable_functions as df

    from kml_satellite.orchestrators.phases import FulfillmentResult

logger = logging.getLogger("kml_satellite.orchestrators.kml_pipeline")

# Re-export polling defaults and _poll_until_ready so existing imports
# (including tests) continue to work.
__all__ = [
    "DEFAULT_DOWNLOAD_BATCH_SIZE",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_POLL_TIMEOUT_SECONDS",
    "DEFAULT_POST_PROCESS_BATCH_SIZE",
    "DEFAULT_RETRY_BASE_SECONDS",
    "_poll_until_ready",
    "orchestrator_function",
]


def orchestrator_function(
    context: df.DurableOrchestrationContext,
) -> Generator[Any, Any, dict[str, object]]:
    """KML processing pipeline orchestrator (thin coordinator).

    Sequences three bounded phases and assembles the final result.

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
    blob_name = str(blob_event.get("blob_name", "<unknown>"))
    timestamp = context.current_utc_datetime.isoformat()

    if not context.is_replaying:
        logger.info(
            "Orchestrator started | instance=%s | blob=%s | correlation_id=%s",
            instance_id,
            blob_name,
            blob_event.get("correlation_id", ""),
        )

    # -----------------------------------------------------------------------
    # Phase 1: Ingestion — parse KML, prepare AOIs, write metadata
    # -----------------------------------------------------------------------
    ingestion = yield from run_ingestion_phase(
        context,
        blob_event,
        timestamp=timestamp,
        instance_id=instance_id,
        blob_name=blob_name,
    )

    # -----------------------------------------------------------------------
    # Phase 2: Acquisition — acquire imagery, poll orders
    # -----------------------------------------------------------------------
    acquisition = yield from run_acquisition_phase(
        context,
        ingestion["aois"],
        blob_event=blob_event,
        instance_id=instance_id,
        blob_name=blob_name,
    )

    # -----------------------------------------------------------------------
    # Phase 3: Fulfillment — download imagery, clip / reproject
    # -----------------------------------------------------------------------
    ready_outcomes = [o for o in acquisition["imagery_outcomes"] if o.get("state") == "ready"]

    # Derive orchard_name from the source KML filename stem.
    _stem = PurePosixPath(blob_name).stem if blob_name else ""
    orchard_name = _stem if _stem and _stem != "<unknown>" else "unknown"

    provider_name = str(blob_event.get("provider_name", "planetary_computer"))

    def _int_cfg(key: str, default: int) -> int:
        raw = blob_event.get(key, default)
        return int(raw) if isinstance(raw, int | float | str) else default

    fulfillment: FulfillmentResult = yield from run_fulfillment_phase(
        context,
        ready_outcomes,
        ingestion["aois"],
        provider_name=provider_name,
        provider_config=blob_event.get("provider_config"),
        orchard_name=orchard_name,
        timestamp=timestamp,
        enable_clipping=bool(blob_event.get("enable_clipping", True)),
        enable_reprojection=bool(blob_event.get("enable_reprojection", True)),
        target_crs=str(blob_event.get("target_crs", "EPSG:4326")),
        download_batch_size=_int_cfg("download_batch_size", DEFAULT_DOWNLOAD_BATCH_SIZE),
        post_process_batch_size=_int_cfg(
            "post_process_batch_size", DEFAULT_POST_PROCESS_BATCH_SIZE
        ),
        instance_id=instance_id,
        blob_name=blob_name,
    )

    # -----------------------------------------------------------------------
    # Result summary
    # -----------------------------------------------------------------------
    result = build_pipeline_summary(
        ingestion,
        acquisition,
        fulfillment,
        instance_id=instance_id,
        blob_event=blob_event,
    )

    if not context.is_replaying:
        logger.info(
            "Orchestrator completed | instance=%s | blob=%s | features=%d",
            instance_id,
            blob_name,
            ingestion["feature_count"],
        )

    return result

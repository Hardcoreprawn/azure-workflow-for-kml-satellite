"""Bounded phase helpers for the KML pipeline orchestrator.

Each phase is a deterministic generator that ``yield``s durable tasks
and returns a typed result contract.  The top-level orchestrator in
``kml_pipeline.py`` coordinates these phases sequentially.

Phases
------
1. **Ingestion** — parse KML, fan-out prepare AOI, write metadata.
2. **Acquisition** — fan-out acquire imagery, concurrent timer-based polling.
3. **Fulfillment** — parallel download imagery, parallel clip / reproject.

Engineering standards:
    PID 7.4.6   (Observability — per-phase telemetry)
    PID FR-5.3  (Durable Functions for long-running workflows)
    PID Section 7.2 (Fan-Out / Fan-In orchestration pattern)

References:
    Issue #54   (Parallelize download and post-process stages)
    Issue #55   (Make polling stage concurrency-aware)
    Issue #59   (Decompose pipeline orchestration)
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, TypedDict

from kml_satellite.core.payload_offload import build_ref_input, is_offloaded

if TYPE_CHECKING:
    from collections.abc import Generator

    import azure.durable_functions as df

logger = logging.getLogger("kml_satellite.orchestrators.phases")


# ---------------------------------------------------------------------------
# Phase result contracts (Issue #59 — typed payloads per phase)
# ---------------------------------------------------------------------------


class IngestionResult(TypedDict):
    """Output contract for the ingestion phase."""

    feature_count: int
    offloaded: bool
    aois: list[dict[str, Any]]
    aoi_count: int
    metadata_results: list[dict[str, Any]]
    metadata_count: int


class AcquisitionResult(TypedDict):
    """Output contract for the acquisition phase."""

    imagery_outcomes: list[dict[str, Any]]
    ready_count: int
    failed_count: int


class FulfillmentResult(TypedDict):
    """Output contract for the fulfillment phase."""

    download_results: list[dict[str, Any]]
    downloads_completed: int
    downloads_succeeded: int
    downloads_failed: int
    post_process_results: list[dict[str, Any]]
    pp_completed: int
    pp_clipped: int
    pp_reprojected: int
    pp_failed: int


# ---------------------------------------------------------------------------
# Polling defaults (PID FR-3.9)
# ---------------------------------------------------------------------------

DEFAULT_POLL_INTERVAL_SECONDS = 30
DEFAULT_POLL_TIMEOUT_SECONDS = 1800  # 30 minutes
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 5

# ---------------------------------------------------------------------------
# Parallelism defaults (Issues #54, #55)
# ---------------------------------------------------------------------------

#: Max concurrent downloads / post-process calls per batch.
DEFAULT_DOWNLOAD_BATCH_SIZE = 10
DEFAULT_POST_PROCESS_BATCH_SIZE = 10
#: Max concurrent poll sub-orchestrations.
DEFAULT_POLL_BATCH_SIZE = 10


# ---------------------------------------------------------------------------
# Phase 1: Ingestion — parse KML, prepare AOIs, write metadata
# ---------------------------------------------------------------------------


def run_ingestion_phase(
    context: df.DurableOrchestrationContext,
    blob_event: dict[str, object],
    *,
    timestamp: str,
    instance_id: str = "",
    blob_name: str = "",
) -> Generator[Any, Any, IngestionResult]:
    """Parse KML → fan-out prepare_aoi → fan-out write_metadata.

    Args:
        context: Durable orchestration context.
        blob_event: Canonical blob event dict.
        timestamp: Shared processing timestamp (ISO 8601).
        instance_id: Orchestration instance ID for logging.
        blob_name: Source blob name for logging.

    Yields:
        Durable activity and task_all calls.

    Returns:
        IngestionResult with feature/AOI/metadata counts and data.
    """
    phase_start = context.current_utc_datetime

    # Step 1: Parse KML
    features_or_ref = yield context.call_activity("parse_kml", blob_event)

    offloaded = is_offloaded(features_or_ref)
    features_ref: dict[str, Any] = {}
    if offloaded:
        features_ref = features_or_ref  # type: ignore[assignment]
        feature_count = int(features_ref.get("count", 0))
    elif isinstance(features_or_ref, list):
        feature_count = len(features_or_ref)
    else:
        feature_count = 0

    if not context.is_replaying:
        logger.info(
            "phase=ingestion step=parse_kml | instance=%s | features=%d | offloaded=%s | blob=%s",
            instance_id,
            feature_count,
            offloaded,
            blob_name,
        )

    # Step 2: Fan-out prepare_aoi
    if offloaded:
        aoi_tasks = [
            context.call_activity("prepare_aoi", build_ref_input(features_ref, i))
            for i in range(feature_count)
        ]
    else:
        aoi_tasks = [
            context.call_activity("prepare_aoi", f)
            for f in (features_or_ref if isinstance(features_or_ref, list) else [])
        ]
    aois = yield context.task_all(aoi_tasks)
    aois_list: list[dict[str, Any]] = aois if isinstance(aois, list) else []
    aoi_count = len(aois_list)

    # Step 3: Write metadata
    metadata_tasks = [
        context.call_activity(
            "write_metadata",
            {
                "aoi": a,
                "processing_id": instance_id,
                "timestamp": timestamp,
            },
        )
        for a in aois_list
    ]
    metadata_results = yield context.task_all(metadata_tasks)
    meta_list: list[dict[str, Any]] = (
        metadata_results if isinstance(metadata_results, list) else []
    )

    duration = (context.current_utc_datetime - phase_start).total_seconds()
    if not context.is_replaying:
        logger.info(
            "phase=ingestion completed | instance=%s | features=%d | "
            "aois=%d | metadata=%d | duration=%.1fs | blob=%s",
            instance_id,
            feature_count,
            aoi_count,
            len(meta_list),
            duration,
            blob_name,
        )

    return IngestionResult(
        feature_count=feature_count,
        offloaded=offloaded,
        aois=aois_list,
        aoi_count=aoi_count,
        metadata_results=meta_list,
        metadata_count=len(meta_list),
    )


# ---------------------------------------------------------------------------
# Phase 2: Acquisition — acquire imagery, poll orders
# ---------------------------------------------------------------------------


def run_acquisition_phase(
    context: df.DurableOrchestrationContext,
    aois: list[dict[str, Any]],
    *,
    blob_event: dict[str, object],
    instance_id: str = "",
    blob_name: str = "",
) -> Generator[Any, Any, AcquisitionResult]:
    """Fan-out acquire_imagery → concurrent timer-based polling (Issue #55).

    Polling is performed concurrently in bounded batches using
    sub-orchestrators.  Each sub-orchestrator runs an independent
    ``_poll_until_ready`` loop so orders are polled in parallel rather
    than sequentially.

    Args:
        context: Durable orchestration context.
        aois: List of AOI dicts from ingestion phase.
        blob_event: Canonical blob event dict (provider config, polling overrides).
        instance_id: Orchestration instance ID for logging.
        blob_name: Source blob name for logging.

    Yields:
        Durable activity, task_all, and sub-orchestrator calls.

    Returns:
        AcquisitionResult with imagery outcomes and ready/failed counts.
    """
    phase_start = context.current_utc_datetime

    # Step 1: Fan-out acquire_imagery
    provider_name = str(blob_event.get("provider_name", "planetary_computer"))
    provider_config_raw = blob_event.get("provider_config")
    filters_raw = blob_event.get("imagery_filters")

    imagery_tasks = [
        context.call_activity(
            "acquire_imagery",
            {
                "aoi": a,
                "provider_name": provider_name,
                "provider_config": provider_config_raw,
                "imagery_filters": filters_raw,
            },
        )
        for a in aois
    ]
    acquisition_results = yield context.task_all(imagery_tasks)

    if not context.is_replaying:
        acq_count = len(acquisition_results) if isinstance(acquisition_results, list) else 0
        logger.info(
            "phase=acquisition step=acquire_imagery | instance=%s | orders=%d | blob=%s",
            instance_id,
            acq_count,
            blob_name,
        )

    # Step 2: Concurrent polling via sub-orchestrators (Issue #55)
    def _int_cfg(key: str, default: int) -> int:
        raw = blob_event.get(key, default)
        return int(raw) if isinstance(raw, int | float | str) else default

    poll_interval = _int_cfg("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
    poll_timeout = _int_cfg("poll_timeout_seconds", DEFAULT_POLL_TIMEOUT_SECONDS)
    max_retries = _int_cfg("max_retries", DEFAULT_MAX_RETRIES)
    retry_base = _int_cfg("retry_base_seconds", DEFAULT_RETRY_BASE_SECONDS)
    poll_batch_size = _int_cfg("poll_batch_size", DEFAULT_POLL_BATCH_SIZE)

    acq_list: list[dict[str, Any]] = (
        acquisition_results if isinstance(acquisition_results, list) else []
    )

    imagery_outcomes: list[dict[str, Any]] = []
    for batch_start in range(0, len(acq_list), poll_batch_size):
        batch = acq_list[batch_start : batch_start + poll_batch_size]

        poll_tasks = [
            context.call_sub_orchestrator(
                "poll_order_suborchestrator",
                {
                    "acquisition": acq,
                    "poll_interval": poll_interval,
                    "poll_timeout": poll_timeout,
                    "max_retries": max_retries,
                    "retry_base": retry_base,
                    "instance_id": instance_id,
                },
                instance_id=f"{instance_id}:poll:{acq.get('order_id', i)}",
            )
            for i, acq in enumerate(batch, start=batch_start)
        ]
        batch_results = yield context.task_all(poll_tasks)

        if isinstance(batch_results, list):
            for r in batch_results:
                imagery_outcomes.append(r if isinstance(r, dict) else {"state": "unknown"})
        elif isinstance(batch_results, dict):
            imagery_outcomes.append(batch_results)

    ready_count = sum(1 for o in imagery_outcomes if o.get("state") == "ready")
    failed_count = len(imagery_outcomes) - ready_count

    duration = (context.current_utc_datetime - phase_start).total_seconds()
    if not context.is_replaying:
        logger.info(
            "phase=acquisition completed | instance=%s | ready=%d/%d | "
            "batches=%d | duration=%.1fs | blob=%s",
            instance_id,
            ready_count,
            len(imagery_outcomes),
            (len(acq_list) + poll_batch_size - 1) // poll_batch_size if acq_list else 0,
            duration,
            blob_name,
        )

    return AcquisitionResult(
        imagery_outcomes=imagery_outcomes,
        ready_count=ready_count,
        failed_count=failed_count,
    )


# ---------------------------------------------------------------------------
# Phase 3: Fulfillment — download imagery, clip / reproject
# ---------------------------------------------------------------------------


def run_fulfillment_phase(
    context: df.DurableOrchestrationContext,
    ready_outcomes: list[dict[str, Any]],
    aois: list[dict[str, Any]],
    *,
    provider_name: str,
    provider_config: object | None,
    orchard_name: str,
    timestamp: str,
    enable_clipping: bool = True,
    enable_reprojection: bool = True,
    target_crs: str = "EPSG:4326",
    download_batch_size: int = DEFAULT_DOWNLOAD_BATCH_SIZE,
    post_process_batch_size: int = DEFAULT_POST_PROCESS_BATCH_SIZE,
    instance_id: str = "",
    blob_name: str = "",
) -> Generator[Any, Any, FulfillmentResult]:
    """Download ready imagery → clip / reproject — in bounded parallel batches.

    Uses ``task_all`` for fan-out parallelism instead of sequential
    per-item processing (Issue #54).  Batch sizes are configurable so
    the orchestrator doesn't overwhelm provider APIs.

    Per-item error isolation is maintained: a single failure doesn't
    abort the entire batch (PID 7.4.2).

    Args:
        context: Durable orchestration context.
        ready_outcomes: Imagery outcomes with ``state == "ready"``.
        aois: Full AOI list for geometry lookup.
        provider_name: Imagery provider name.
        provider_config: Optional provider configuration overrides.
        orchard_name: Orchard/project name for blob path generation.
        timestamp: Shared processing timestamp (ISO 8601).
        enable_clipping: Whether to clip to AOI polygon.
        enable_reprojection: Whether to reproject if CRS differs.
        target_crs: Target CRS for reprojection.
        download_batch_size: Max concurrent downloads per batch (default 10).
        post_process_batch_size: Max concurrent post-process ops per batch (default 10).
        instance_id: Orchestration instance ID for logging.
        blob_name: Source blob name for logging.

    Yields:
        Durable activity and task_all calls.

    Returns:
        FulfillmentResult with download and post-process outcomes.
    """
    phase_start = context.current_utc_datetime

    # Step 1: Download imagery — bounded parallel batches (Issue #54)
    download_results: list[dict[str, Any]] = []

    for batch_start in range(0, len(ready_outcomes), download_batch_size):
        batch = ready_outcomes[batch_start : batch_start + download_batch_size]
        dl_tasks = [
            context.call_activity(
                "download_imagery",
                {
                    "imagery_outcome": outcome,
                    "provider_name": provider_name,
                    "provider_config": provider_config,
                    "orchard_name": orchard_name,
                    "timestamp": timestamp,
                },
            )
            for outcome in batch
        ]

        try:
            batch_results = yield context.task_all(dl_tasks)
        except Exception as exc:
            if not context.is_replaying:
                logger.exception(
                    "phase=fulfillment step=download | instance=%s | blob=%s | "
                    "batch_error=%s | batch_size=%d",
                    instance_id,
                    blob_name,
                    exc,
                    len(batch),
                )
            for outcome in batch:
                download_results.append(_download_error_dict(outcome, str(exc)))
            continue

        if isinstance(batch_results, list):
            for i, result in enumerate(batch_results):
                outcome = batch[i]
                if isinstance(result, dict):
                    download_results.append(result)
                else:
                    download_results.append(
                        _download_error_dict(
                            outcome,
                            f"Unexpected non-dict result: {result!r}",
                            state="unknown",
                        )
                    )
        elif isinstance(batch_results, dict):
            download_results.append(batch_results)

    if not context.is_replaying:
        logger.info(
            "phase=fulfillment step=download | instance=%s | downloaded=%d/%d | "
            "batches=%d | blob=%s",
            instance_id,
            len(download_results),
            len(ready_outcomes),
            (len(ready_outcomes) + download_batch_size - 1) // download_batch_size
            if ready_outcomes
            else 0,
            blob_name,
        )

    # Step 2: Post-process imagery — bounded parallel batches (Issue #54)
    # Build feature_name → AOI lookup for geometry retrieval
    aoi_by_feature: dict[str, dict[str, Any]] = {}
    for a in aois:
        if isinstance(a, dict):
            fname = str(a.get("feature_name", ""))
            if fname:
                aoi_by_feature[fname] = a

    successful_downloads = [d for d in download_results if d.get("state") != "failed"]

    post_process_results: list[dict[str, Any]] = []
    for batch_start in range(0, len(successful_downloads), post_process_batch_size):
        batch = successful_downloads[batch_start : batch_start + post_process_batch_size]
        pp_tasks = [
            context.call_activity(
                "post_process_imagery",
                {
                    "download_result": dl_result,
                    "aoi": aoi_by_feature.get(str(dl_result.get("aoi_feature_name", "")), {}),
                    "orchard_name": orchard_name,
                    "timestamp": timestamp,
                    "target_crs": target_crs,
                    "enable_clipping": enable_clipping,
                    "enable_reprojection": enable_reprojection,
                },
            )
            for dl_result in batch
        ]

        try:
            batch_results = yield context.task_all(pp_tasks)
        except Exception as exc:
            if not context.is_replaying:
                logger.exception(
                    "phase=fulfillment step=post_process | instance=%s | blob=%s | "
                    "batch_error=%s | batch_size=%d",
                    instance_id,
                    blob_name,
                    exc,
                    len(batch),
                )
            for dl_result in batch:
                post_process_results.append(_post_process_error_dict(dl_result, str(exc)))
            continue

        if isinstance(batch_results, list):
            for i, pp_result in enumerate(batch_results):
                dl_result = batch[i]
                if isinstance(pp_result, dict):
                    post_process_results.append(pp_result)
                else:
                    post_process_results.append(
                        _post_process_error_dict(
                            dl_result,
                            f"Unexpected non-dict result: {pp_result!r}",
                            state="unknown",
                        )
                    )
        elif isinstance(batch_results, dict):
            post_process_results.append(batch_results)

    downloads_failed = sum(1 for d in download_results if d.get("state") == "failed")
    pp_clipped = sum(1 for p in post_process_results if p.get("clipped"))
    pp_reprojected = sum(1 for p in post_process_results if p.get("reprojected"))
    pp_failed = sum(1 for p in post_process_results if p.get("state") == "failed")

    duration = (context.current_utc_datetime - phase_start).total_seconds()
    if not context.is_replaying:
        logger.info(
            "phase=fulfillment completed | instance=%s | downloads=%d | "
            "clipped=%d | reprojected=%d | failed=%d | "
            "dl_batches=%d | pp_batches=%d | duration=%.1fs | blob=%s",
            instance_id,
            len(download_results),
            pp_clipped,
            pp_reprojected,
            pp_failed,
            (len(ready_outcomes) + download_batch_size - 1) // download_batch_size
            if ready_outcomes
            else 0,
            (len(successful_downloads) + post_process_batch_size - 1) // post_process_batch_size
            if successful_downloads
            else 0,
            duration,
            blob_name,
        )

    return FulfillmentResult(
        download_results=download_results,
        downloads_completed=len(download_results),
        downloads_succeeded=len(download_results) - downloads_failed,
        downloads_failed=downloads_failed,
        post_process_results=post_process_results,
        pp_completed=len(post_process_results),
        pp_clipped=pp_clipped,
        pp_reprojected=pp_reprojected,
        pp_failed=pp_failed,
    )


def _download_error_dict(
    outcome: dict[str, Any],
    error: str,
    *,
    state: str = "failed",
) -> dict[str, Any]:
    """Build a contract-shaped error dict for a failed download."""
    return {
        "state": state,
        "order_id": str(outcome.get("order_id", "")),
        "scene_id": str(outcome.get("scene_id", "")),
        "provider": str(outcome.get("provider", "")),
        "aoi_feature_name": str(outcome.get("aoi_feature_name", "")),
        "blob_path": "",
        "adapter_blob_path": "",
        "container": "",
        "size_bytes": 0,
        "content_type": "",
        "download_duration_seconds": 0.0,
        "retry_count": 0,
        "error": error,
    }


def _post_process_error_dict(
    dl_result: dict[str, Any],
    error: str,
    *,
    state: str = "failed",
) -> dict[str, Any]:
    """Build a contract-shaped error dict for a failed post-process."""
    return {
        "state": state,
        "order_id": dl_result.get("order_id", ""),
        "source_blob_path": dl_result.get("blob_path", ""),
        "clipped_blob_path": "",
        "container": dl_result.get("container", ""),
        "clipped": False,
        "reprojected": False,
        "source_crs": "",
        "target_crs": "",
        "source_size_bytes": 0,
        "output_size_bytes": 0,
        "processing_duration_seconds": 0.0,
        "clip_error": error,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def build_pipeline_summary(
    ingestion: IngestionResult,
    acquisition: AcquisitionResult,
    fulfillment: FulfillmentResult,
    *,
    instance_id: str,
    blob_event: dict[str, object],
) -> dict[str, object]:
    """Build the final orchestration result from phase outputs.

    Args:
        ingestion: Result from the ingestion phase.
        acquisition: Result from the acquisition phase.
        fulfillment: Result from the fulfillment phase.
        instance_id: Orchestration instance ID.
        blob_event: Original blob event dict.

    Returns:
        Dict summarising the full pipeline run.
    """
    blob_name = blob_event.get("blob_name", "<unknown>")

    status_label = (
        "completed"
        if acquisition["failed_count"] == 0
        and fulfillment["downloads_failed"] == 0
        and fulfillment["downloads_succeeded"] == acquisition["ready_count"]
        and fulfillment["pp_failed"] == 0
        else "partial_imagery"
    )

    return {
        "status": status_label,
        "instance_id": instance_id,
        "blob_name": blob_name,
        "blob_url": blob_event.get("blob_url", ""),
        "feature_count": ingestion["feature_count"],
        "aoi_count": ingestion["aoi_count"],
        "metadata_count": ingestion["metadata_count"],
        "imagery_ready": acquisition["ready_count"],
        "imagery_failed": acquisition["failed_count"],
        "downloads_completed": fulfillment["downloads_completed"],
        "post_process_completed": fulfillment["pp_completed"],
        "post_process_clipped": fulfillment["pp_clipped"],
        "post_process_reprojected": fulfillment["pp_reprojected"],
        "imagery_outcomes": acquisition["imagery_outcomes"],
        "download_results": fulfillment["download_results"],
        "post_process_results": fulfillment["post_process_results"],
        "message": (
            f"Parsed {ingestion['feature_count']} feature(s), "
            f"prepared {ingestion['aoi_count']} AOI(s), "
            f"wrote {ingestion['metadata_count']} metadata record(s), "
            f"imagery ready={acquisition['ready_count']} "
            f"failed={acquisition['failed_count']}, "
            f"downloaded={fulfillment['downloads_completed']}, "
            f"clipped={fulfillment['pp_clipped']} "
            f"reprojected={fulfillment['pp_reprojected']}."
        ),
    }


# ---------------------------------------------------------------------------
# Polling sub-orchestration (moved from kml_pipeline.py)
# ---------------------------------------------------------------------------


def _poll_until_ready(
    context: df.DurableOrchestrationContext,
    acquisition: dict[str, Any],
    *,
    poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS,
    poll_timeout: int = DEFAULT_POLL_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_base: int = DEFAULT_RETRY_BASE_SECONDS,
    instance_id: str = "",
) -> Generator[Any, Any, dict[str, Any]]:
    """Poll an imagery order until it reaches a terminal state.

    Uses ``context.create_timer()`` for zero-compute-cost waits between
    polls.  Implements exponential backoff on transient errors.

    Args:
        context: Durable Functions orchestration context.
        acquisition: Dict from ``acquire_imagery`` activity with
            ``order_id``, ``provider``, ``scene_id``, etc.
        poll_interval: Seconds between polls (default 30).
        poll_timeout: Maximum total wait in seconds (default 1800).
        max_retries: Max retries on transient poll errors (default 3).
        retry_base: Exponential backoff base in seconds (default 5).
        instance_id: Orchestration instance ID for logging.

    Returns:
        A dict describing the final outcome:
        - ``state``: ``"ready"`` | ``"failed"`` | ``"cancelled"`` |
          ``"acquisition_timeout"``
        - ``order_id``, ``scene_id``, ``provider``
        - ``poll_count``, ``elapsed_seconds``
        - ``error``: Error message (if any)

    Yields:
        Durable Functions tasks (activities and timers).
    """
    order_id = str(acquisition.get("order_id", ""))
    scene_id = str(acquisition.get("scene_id", ""))
    provider = str(acquisition.get("provider", ""))
    feature_name = str(acquisition.get("aoi_feature_name", ""))

    deadline = context.current_utc_datetime + timedelta(seconds=poll_timeout)
    poll_count = 0
    retry_count = 0

    while context.current_utc_datetime < deadline:
        poll_count += 1

        try:
            poll_result = yield context.call_activity(
                "poll_order",
                {"order_id": order_id, "provider": provider},
            )
            retry_count = 0
        except Exception as exc:
            retry_count += 1
            if retry_count > max_retries:
                if not context.is_replaying:
                    logger.error(
                        "Poll retries exhausted | instance=%s | order=%s | "
                        "feature=%s | retries=%d | error=%s",
                        instance_id,
                        order_id,
                        feature_name,
                        retry_count,
                        exc,
                    )
                elapsed = (
                    context.current_utc_datetime - (deadline - timedelta(seconds=poll_timeout))
                ).total_seconds()
                return {
                    "state": "failed",
                    "order_id": order_id,
                    "scene_id": scene_id,
                    "provider": provider,
                    "aoi_feature_name": feature_name,
                    "poll_count": poll_count,
                    "elapsed_seconds": elapsed,
                    "error": f"Poll retries exhausted ({max_retries}): {exc}",
                }

            backoff = retry_base * (2 ** (retry_count - 1))
            if not context.is_replaying:
                logger.warning(
                    "Poll error (retry %d/%d) | instance=%s | order=%s | backoff=%ds | error=%s",
                    retry_count,
                    max_retries,
                    instance_id,
                    order_id,
                    backoff,
                    exc,
                )
            fire_at = context.current_utc_datetime + timedelta(seconds=backoff)
            yield context.create_timer(fire_at)
            continue

        state = str(poll_result.get("state", ""))
        is_terminal = bool(poll_result.get("is_terminal", False))

        if not context.is_replaying:
            logger.info(
                "Poll result | instance=%s | order=%s | feature=%s | state=%s | poll_count=%d",
                instance_id,
                order_id,
                feature_name,
                state,
                poll_count,
            )

        if is_terminal:
            elapsed = (
                context.current_utc_datetime - (deadline - timedelta(seconds=poll_timeout))
            ).total_seconds()
            return {
                "state": state,
                "order_id": order_id,
                "scene_id": scene_id,
                "provider": provider,
                "aoi_feature_name": feature_name,
                "poll_count": poll_count,
                "elapsed_seconds": elapsed,
                "error": poll_result.get("message", "") if state != "ready" else "",
            }

        fire_at = context.current_utc_datetime + timedelta(seconds=poll_interval)
        yield context.create_timer(fire_at)

    elapsed = float(poll_timeout)
    if not context.is_replaying:
        logger.warning(
            "Poll timeout | instance=%s | order=%s | feature=%s | timeout=%ds | poll_count=%d",
            instance_id,
            order_id,
            feature_name,
            poll_timeout,
            poll_count,
        )

    return {
        "state": "acquisition_timeout",
        "order_id": order_id,
        "scene_id": scene_id,
        "provider": provider,
        "aoi_feature_name": feature_name,
        "poll_count": poll_count,
        "elapsed_seconds": elapsed,
        "error": f"Polling timed out after {poll_timeout}s ({poll_count} polls)",
    }

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
from collections.abc import Callable
from functools import partial
from itertools import batched
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

from kml_satellite.core.config import config_get_int
from kml_satellite.core.constants import DEFAULT_OUTPUT_CONTAINER
from kml_satellite.core.payload_offload import build_ref_input, is_offloaded
from kml_satellite.core.states import WorkflowState
from kml_satellite.orchestrators.error_helpers import (
    download_error_dict,
    post_process_error_dict,
)
from kml_satellite.orchestrators.polling import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_POLL_BATCH_SIZE,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_RETRY_BASE_SECONDS,
)

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

DEFAULT_DOWNLOAD_BATCH_SIZE = 10
DEFAULT_POST_PROCESS_BATCH_SIZE = 10
#: Max concurrent poll sub-orchestrations.
#: (DEFAULT_POLL_BATCH_SIZE is now imported from polling.py)


# ---------------------------------------------------------------------------
# Fulfillment stage configuration

# Type aliases for batch processing callables
TaskInputBuilder = Callable[[dict[str, Any]], dict[str, Any]]
"""Builds activity input dict from a batch item dict."""


class ErrorBuilder(Protocol):
    """Protocol for error dict builders.

    Functions matching this protocol build error result dicts from
    a batch item and error message, with optional state override.
    """

    def __call__(
        self,
        __item: dict[str, Any],
        __error: str,
        *,
        state: str = WorkflowState.FAILED,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------


class _BatchStageConfig(TypedDict):
    """Configuration for a fulfillment batch processing stage."""

    items: list[dict[str, Any]]
    batch_size: int
    activity_name: str
    task_input_builder: TaskInputBuilder
    error_builder: ErrorBuilder
    step_name: str


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
    tenant_id: str = "",
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
                "tenant_id": tenant_id,
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
    poll_interval = config_get_int(
        blob_event, "poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS
    )
    poll_timeout = config_get_int(blob_event, "poll_timeout_seconds", DEFAULT_POLL_TIMEOUT_SECONDS)
    max_retries = config_get_int(blob_event, "max_retries", DEFAULT_MAX_RETRIES)
    retry_base = config_get_int(blob_event, "retry_base_seconds", DEFAULT_RETRY_BASE_SECONDS)
    poll_batch_size = config_get_int(blob_event, "poll_batch_size", DEFAULT_POLL_BATCH_SIZE)

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
                instance_id=f"{instance_id}:poll:{acq.get('order_id') or i}",
            )
            for i, acq in enumerate(batch, start=batch_start)
        ]
        batch_results = yield context.task_all(poll_tasks)

        if isinstance(batch_results, list):
            for r in batch_results:
                imagery_outcomes.append(r if isinstance(r, dict) else {"state": "unknown"})
        elif isinstance(batch_results, dict):
            imagery_outcomes.append(batch_results)

    ready_count = sum(1 for o in imagery_outcomes if o.get("state") == WorkflowState.READY)
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


def _calculate_batch_count(total_items: int, batch_size: int) -> int:
    """Calculate number of batches needed for given items and batch size.

    Args:
        total_items: Total number of items to process.
        batch_size: Maximum items per batch.

    Returns:
        Number of batches required (0 if no items).
    """
    if total_items == 0:
        return 0
    return (total_items + batch_size - 1) // batch_size


def _classify_result_by_state(result: dict[str, Any]) -> str:
    """Classify result using pattern matching on state field.

    Uses Python 3.10+ match/case with StrEnum for type-safe state handling.

    Args:
        result: Result dict with optional 'state' field.

    Returns:
        Classification: 'success', 'failed', or 'unknown'.
    """
    state = result.get("state")
    match state:
        case WorkflowState.READY | WorkflowState.COMPLETED | WorkflowState.SUCCESS:
            return "success"
        case WorkflowState.FAILED | WorkflowState.ERROR:
            return "failed"
        case _:
            return "unknown"


def _filter_successful_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter results to only successful ones.

    Uses WorkflowState enum for type-safe filtering.

    Args:
        results: List of result dicts.

    Returns:
        List of results where state is not failed.
    """
    return [r for r in results if not WorkflowState.is_failure(r.get("state", ""))]


def _validate_batch_results(
    batch_results: Any,
    batch: list[dict[str, Any]],
    error_builder: ErrorBuilder,
) -> list[dict[str, Any]]:
    """Validate and normalize batch results from task_all.

    Handles both list and dict results from task_all, ensuring all results
    are valid dicts. Invalid results are converted to error dicts.

    Args:
        batch_results: Raw results from context.task_all().
        batch: Original batch items (for error context).
        error_builder: Function to build error dicts (download_error_dict or post_process_error_dict).

    Returns:
        List of validated result dicts.
    """
    validated: list[dict[str, Any]] = []

    if isinstance(batch_results, list):
        for i, result in enumerate(batch_results):
            item = batch[i]
            if isinstance(result, dict):
                validated.append(result)
            else:
                validated.append(
                    error_builder(
                        item,
                        f"Unexpected non-dict result: {result!r}",
                        state="unknown",
                    )
                )
    elif isinstance(batch_results, dict):
        validated.append(batch_results)

    return validated


def _execute_activity_batch(
    context: df.DurableOrchestrationContext,
    activity_name: str,
    batch: list[dict[str, Any]],
    task_input_builder: TaskInputBuilder,
    error_builder: ErrorBuilder,
    instance_id: str,
    blob_name: str,
    step_name: str,
) -> Generator[Any, Any, list[dict[str, Any]]]:
    """Execute a batch of activity tasks with error handling.

    Generic batch executor that creates tasks, executes them with task_all,
    handles errors, and validates results.

    Args:
        context: Durable orchestration context.
        activity_name: Name of the activity to call.
        batch: Batch items to process.
        task_input_builder: Function to build activity input from batch item.
        error_builder: Function to build error dicts on failure.
        instance_id: Orchestration instance ID for logging.
        blob_name: Source blob name for logging.
        step_name: Step name for logging (e.g., "download", "post_process").

    Yields:
        task_all call.

    Returns:
        List of validated result dicts.
    """
    tasks = [context.call_activity(activity_name, task_input_builder(item)) for item in batch]

    try:
        batch_results = yield context.task_all(tasks)
    except Exception as exc:
        if not context.is_replaying:
            logger.exception(
                "phase=fulfillment step=%s | instance=%s | blob=%s | "
                "batch_error=%s | batch_size=%d",
                step_name,
                instance_id,
                blob_name,
                exc,
                len(batch),
            )
        return [error_builder(item, str(exc)) for item in batch]

    return _validate_batch_results(batch_results, batch, error_builder)


def _process_all_batches(
    context: df.DurableOrchestrationContext,
    items: list[dict[str, Any]],
    batch_size: int,
    activity_name: str,
    task_input_builder: TaskInputBuilder,
    error_builder: ErrorBuilder,
    instance_id: str,
    blob_name: str,
    step_name: str,
) -> Generator[Any, Any, list[dict[str, Any]]]:
    """Process all items in batches, accumulating results.

    Uses itertools.batched() (Python 3.12+) for cleaner batch iteration.

    Args:
        context: Durable orchestration context.
        items: Items to process in batches.
        batch_size: Maximum items per batch.
        activity_name: Name of the activity to call.
        task_input_builder: Function to build activity input from item.
        error_builder: Function to build error dicts on failure.
        instance_id: Orchestration instance ID for logging.
        blob_name: Source blob name for logging.
        step_name: Step name for logging (e.g., "download", "post_process").

    Yields:
        task_all calls for each batch.

    Returns:
        Accumulated list of all batch results.
    """
    all_results: list[dict[str, Any]] = []

    # Use itertools.batched() instead of manual range slicing
    for batch in batched(items, batch_size):
        batch_list = list(batch)  # Convert tuple to list for compatibility
        batch_results = yield from _execute_activity_batch(
            context=context,
            activity_name=activity_name,
            batch=batch_list,
            task_input_builder=task_input_builder,
            error_builder=error_builder,
            instance_id=instance_id,
            blob_name=blob_name,
            step_name=step_name,
        )
        all_results.extend(batch_results)

    return all_results


def _execute_stage(
    context: df.DurableOrchestrationContext,
    stage: _BatchStageConfig,
    instance_id: str,
    blob_name: str,
) -> Generator[Any, Any, list[dict[str, Any]]]:
    """Execute a configured pipeline stage.

    Unpacks stage configuration and dispatches to batch processor.

    Args:
        context: Durable orchestration context.
        stage: Stage configuration with items, batch_size, etc.
        instance_id: Orchestration instance ID for logging.
        blob_name: Source blob name for logging.

    Yields:
        task_all calls for each batch.

    Returns:
        List of all stage results.
    """
    return (
        yield from _process_all_batches(
            context=context,
            items=stage["items"],
            batch_size=stage["batch_size"],
            activity_name=stage["activity_name"],
            task_input_builder=stage["task_input_builder"],
            error_builder=stage["error_builder"],
            instance_id=instance_id,
            blob_name=blob_name,
            step_name=stage["step_name"],
        )
    )


def _build_aoi_lookup(aois: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build feature_name → AOI dict for fast geometry lookup.

    Uses operator.itemgetter for cleaner dict access.

    Args:
        aois: List of AOI dicts with feature_name keys.

    Returns:
        Dict mapping feature_name to full AOI dict.
    """
    get_feature_name = itemgetter("feature_name")
    return {
        str(get_feature_name(a)): a for a in aois if isinstance(a, dict) and a.get("feature_name")
    }


def _count_results_by_state(
    results: list[dict[str, Any]], field: str, value: str | int | float | bool | None
) -> int:
    """Count results where field equals value.

    Uses operator.itemgetter for cleaner field access.

    Args:
        results: List of result dicts.
        field: Field name to check.
        value: Value to match.

    Returns:
        Count of matching results.
    """
    # Note: dict.get() still needed for safety with missing keys
    return sum(1 for r in results if r.get(field) == value)


def _calculate_result_metrics(
    download_results: list[dict[str, Any]],
    post_process_results: list[dict[str, Any]],
) -> dict[str, int]:
    """Calculate summary metrics from stage results.

    Uses functional composition for cleaner metric calculation.

    Args:
        download_results: Results from download stage.
        post_process_results: Results from post-process stage.

    Returns:
        Dict with failed/succeeded/clipped/reprojected counts.
    """
    # Create specialized counters using partial application
    count_failed = partial(_count_results_by_state, field="state", value=WorkflowState.FAILED)
    count_true = partial(_count_results_by_state, value=True)

    return {
        "downloads_failed": count_failed(download_results),
        "pp_clipped": count_true(post_process_results, field="clipped"),
        "pp_reprojected": count_true(post_process_results, field="reprojected"),
        "pp_failed": count_failed(post_process_results),
    }


def run_fulfillment_phase(
    context: df.DurableOrchestrationContext,
    ready_outcomes: list[dict[str, Any]],
    aois: list[dict[str, Any]],
    *,
    provider_name: str,
    provider_config: object | None,
    project_name: str,
    timestamp: str,
    enable_clipping: bool = True,
    enable_reprojection: bool = True,
    target_crs: str = "EPSG:4326",
    download_batch_size: int = DEFAULT_DOWNLOAD_BATCH_SIZE,
    post_process_batch_size: int = DEFAULT_POST_PROCESS_BATCH_SIZE,
    instance_id: str = "",
    blob_name: str = "",
    output_container: str = DEFAULT_OUTPUT_CONTAINER,
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
        project_name: Project name for blob path generation.
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

    # Normalize batch sizes
    download_batch_size = max(1, download_batch_size)
    post_process_batch_size = max(1, post_process_batch_size)

    # Build feature_name → AOI lookup for geometry retrieval
    aoi_by_feature = _build_aoi_lookup(aois)

    # Configure pipeline stages declaratively
    stages: dict[str, _BatchStageConfig] = {
        "download": {
            "items": ready_outcomes,
            "batch_size": download_batch_size,
            "activity_name": "download_imagery",
            "task_input_builder": lambda outcome: {
                "imagery_outcome": outcome,
                "provider_name": provider_name,
                "provider_config": provider_config,
                "project_name": project_name,
                "timestamp": timestamp,
                "output_container": output_container,
            },
            "error_builder": download_error_dict,
            "step_name": "download",
        },
        "post_process": {
            "items": [],  # Will be filled after download
            "batch_size": post_process_batch_size,
            "activity_name": "post_process_imagery",
            "task_input_builder": lambda dl_result: {
                "download_result": dl_result,
                "aoi": aoi_by_feature.get(str(dl_result.get("aoi_feature_name", "")), {}),
                "project_name": project_name,
                "timestamp": timestamp,
                "target_crs": target_crs,
                "enable_clipping": enable_clipping,
                "enable_reprojection": enable_reprojection,
                "output_container": output_container,
            },
            "error_builder": post_process_error_dict,
            "step_name": "post_process",
        },
    }

    # Execute download stage
    download_results = yield from _execute_stage(
        context=context,
        stage=stages["download"],
        instance_id=instance_id,
        blob_name=blob_name,
    )

    if not context.is_replaying:
        logger.info(
            "phase=fulfillment step=download | instance=%s | downloaded=%d/%d | "
            "batches=%d | blob=%s",
            instance_id,
            len(download_results),
            len(ready_outcomes),
            _calculate_batch_count(len(ready_outcomes), download_batch_size),
            blob_name,
        )

    # Execute post-process stage (only on successful downloads)
    successful_downloads = _filter_successful_results(download_results)
    stages["post_process"]["items"] = successful_downloads

    post_process_results = yield from _execute_stage(
        context=context,
        stage=stages["post_process"],
        instance_id=instance_id,
        blob_name=blob_name,
    )

    # Calculate result metrics
    metrics = _calculate_result_metrics(download_results, post_process_results)

    duration = (context.current_utc_datetime - phase_start).total_seconds()
    if not context.is_replaying:
        logger.info(
            "phase=fulfillment completed | instance=%s | downloads=%d | "
            "clipped=%d | reprojected=%d | failed=%d | "
            "dl_batches=%d | pp_batches=%d | duration=%.1fs | blob=%s",
            instance_id,
            len(download_results),
            metrics["pp_clipped"],
            metrics["pp_reprojected"],
            metrics["pp_failed"],
            _calculate_batch_count(len(ready_outcomes), download_batch_size),
            _calculate_batch_count(len(successful_downloads), post_process_batch_size),
            duration,
            blob_name,
        )

    return FulfillmentResult(
        download_results=download_results,
        downloads_completed=len(download_results),
        downloads_succeeded=len(download_results) - metrics["downloads_failed"],
        downloads_failed=metrics["downloads_failed"],
        post_process_results=post_process_results,
        pp_completed=len(post_process_results),
        pp_clipped=metrics["pp_clipped"],
        pp_reprojected=metrics["pp_reprojected"],
        pp_failed=metrics["pp_failed"],
    )


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

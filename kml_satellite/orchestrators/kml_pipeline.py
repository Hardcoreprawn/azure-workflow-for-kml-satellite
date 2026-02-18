"""Durable Functions orchestrator for the KML processing pipeline.

Receives a ``BlobEvent`` dict from the trigger function and coordinates
the pipeline steps:

1. Parse KML (activity) — extract features
2. Fan-out per polygon — prepare AOI + acquire imagery
3. Timer-based polling loop — poll order status with configurable intervals
4. Fan-in — collect results and write metadata

Polling configuration (via ``blob_event`` or defaults):
    ``poll_interval_seconds``: Seconds between polls (default 30).
    ``poll_timeout_seconds``: Maximum total wait (default 1800 = 30 min).
    ``max_retries``: Max retries on transient errors (default 3).
    ``retry_base_seconds``: Exponential backoff base (default 5).

References:
    PID FR-3.9  (poll until completion with timeout)
    PID FR-5.3  (Durable Functions for long-running workflows)
    PID FR-6.4  (exponential backoff, configurable max retries, default 3)
    PID Section 7.2 (Fan-Out / Fan-In orchestration pattern)
    PID Section 7.4.2 (Fail Loudly, Fail Safely — graceful degradation)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

    import azure.durable_functions as df

logger = logging.getLogger("kml_satellite.orchestrators.kml_pipeline")

# ---------------------------------------------------------------------------
# Polling defaults (PID FR-3.9, FR-6.4)
# ---------------------------------------------------------------------------

DEFAULT_POLL_INTERVAL_SECONDS = 30
DEFAULT_POLL_TIMEOUT_SECONDS = 1800  # 30 minutes
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 5


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
    # Phase 4: Acquire imagery — search + order (M-2.3)
    # -----------------------------------------------------------------------
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
            "Imagery acquired | instance=%s | orders=%d | blob=%s",
            instance_id,
            acq_count,
            blob_name,
        )

    # -----------------------------------------------------------------------
    # Phase 5: Timer-based polling loop (M-2.3, FR-3.9)
    # -----------------------------------------------------------------------
    def _int_cfg(key: str, default: int) -> int:
        raw = blob_event.get(key, default)
        return int(raw) if isinstance(raw, int | float | str) else default

    poll_interval = _int_cfg("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
    poll_timeout = _int_cfg("poll_timeout_seconds", DEFAULT_POLL_TIMEOUT_SECONDS)
    max_retries = _int_cfg("max_retries", DEFAULT_MAX_RETRIES)
    retry_base = _int_cfg("retry_base_seconds", DEFAULT_RETRY_BASE_SECONDS)

    imagery_outcomes: list[dict[str, Any]] = []

    for acq in acquisition_results if isinstance(acquisition_results, list) else []:
        outcome = yield from _poll_until_ready(
            context,
            acq,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
            max_retries=max_retries,
            retry_base=retry_base,
            instance_id=instance_id,
        )
        imagery_outcomes.append(outcome)

    if not context.is_replaying:
        ready_count = sum(1 for o in imagery_outcomes if o.get("state") == "ready")
        logger.info(
            "Polling complete | instance=%s | ready=%d/%d | blob=%s",
            instance_id,
            ready_count,
            len(imagery_outcomes),
            blob_name,
        )

    # -----------------------------------------------------------------------
    # Phase 6: Download imagery for ready orders (M-2.4, FR-3.10, FR-4.2)
    # -----------------------------------------------------------------------
    ready_outcomes = [o for o in imagery_outcomes if o.get("state") == "ready"]

    # Derive orchard_name from the source KML filename stem
    # (same heuristic as metadata — see models.metadata._extract_orchard_name)
    _blob_name_str = str(blob_name)
    if "." in _blob_name_str:
        from pathlib import PurePosixPath

        orchard_name = PurePosixPath(_blob_name_str).stem
    else:
        orchard_name = _blob_name_str if _blob_name_str != "<unknown>" else ""

    # Sequential downloads with per-order error handling so a single
    # failure doesn't abort the entire orchestration (PID 7.4.2).
    download_results: list[dict[str, Any]] = []
    for outcome in ready_outcomes:
        try:
            result = yield context.call_activity(
                "download_imagery",
                {
                    "imagery_outcome": outcome,
                    "provider_name": provider_name,
                    "provider_config": provider_config_raw,
                    "orchard_name": orchard_name,
                    "timestamp": timestamp,
                },
            )
            if isinstance(result, dict):
                download_results.append(result)
            else:
                download_results.append(
                    {
                        "state": "unknown",
                        "imagery_outcome": outcome,
                        "result": result,
                    }
                )
        except Exception as exc:
            if not context.is_replaying:
                logger.exception(
                    "Download failed for outcome | instance=%s | blob=%s | error=%s",
                    instance_id,
                    blob_name,
                    exc,
                )
            download_results.append(
                {
                    "state": "failed",
                    "imagery_outcome": outcome,
                    "error": str(exc),
                }
            )

    if not context.is_replaying:
        logger.info(
            "Downloads complete | instance=%s | downloaded=%d/%d | blob=%s",
            instance_id,
            len(download_results),
            len(ready_outcomes),
            blob_name,
        )

    # -----------------------------------------------------------------------
    # Phase 7: Post-process imagery — clip + reproject (M-2.5, FR-3.11, FR-3.12)
    # -----------------------------------------------------------------------
    # Build a mapping from order_id → AOI dict for clipping geometry.
    # Each acquisition result carries aoi_feature_name; we match it to the
    # original AOI used for that acquisition.
    enable_clipping = bool(blob_event.get("enable_clipping", True))
    enable_reprojection = bool(blob_event.get("enable_reprojection", True))
    target_crs = str(blob_event.get("target_crs", "EPSG:4326"))

    # Build a lookup from feature_name → AOI dict for geometry retrieval
    aoi_by_feature: dict[str, dict[str, Any]] = {}
    if isinstance(aois, list):
        for a in aois:
            if isinstance(a, dict):
                fname = str(a.get("feature_name", ""))
                if fname:
                    aoi_by_feature[fname] = a

    # Only post-process successful downloads (not state="failed")
    successful_downloads = [d for d in download_results if d.get("state") != "failed"]

    post_process_results: list[dict[str, Any]] = []
    for dl_result in successful_downloads:
        # Find the matching AOI for this download
        dl_feature = str(dl_result.get("aoi_feature_name", ""))
        matching_aoi = aoi_by_feature.get(dl_feature, {})

        try:
            pp_result = yield context.call_activity(
                "post_process_imagery",
                {
                    "download_result": dl_result,
                    "aoi": matching_aoi,
                    "orchard_name": orchard_name,
                    "timestamp": timestamp,
                    "target_crs": target_crs,
                    "enable_clipping": enable_clipping,
                    "enable_reprojection": enable_reprojection,
                },
            )
            if isinstance(pp_result, dict):
                post_process_results.append(pp_result)
            else:
                post_process_results.append(
                    {
                        "state": "unknown",
                        "download_result": dl_result,
                        "result": pp_result,
                    }
                )
        except Exception as exc:
            if not context.is_replaying:
                logger.exception(
                    "Post-processing failed | instance=%s | order=%s | error=%s",
                    instance_id,
                    dl_result.get("order_id", ""),
                    exc,
                )
            post_process_results.append(
                {
                    "state": "failed",
                    "order_id": dl_result.get("order_id", ""),
                    "error": str(exc),
                    "clipped": False,
                    "reprojected": False,
                }
            )

    if not context.is_replaying:
        clipped_count = sum(1 for p in post_process_results if p.get("clipped"))
        logger.info(
            "Post-processing complete | instance=%s | processed=%d | clipped=%d | blob=%s",
            instance_id,
            len(post_process_results),
            clipped_count,
            blob_name,
        )

    # -----------------------------------------------------------------------
    # Result summary
    # -----------------------------------------------------------------------
    feature_count = len(features) if isinstance(features, list) else 0
    aoi_count = len(aois) if isinstance(aois, list) else 0
    metadata_count = len(metadata_results) if isinstance(metadata_results, list) else 0
    imagery_ready = sum(1 for o in imagery_outcomes if o.get("state") == "ready")
    imagery_failed = len(imagery_outcomes) - imagery_ready
    downloads_completed = len(download_results)
    downloads_failed = sum(1 for d in download_results if d.get("state") == "failed")
    downloads_succeeded = downloads_completed - downloads_failed
    pp_completed = len(post_process_results)
    pp_clipped = sum(1 for p in post_process_results if p.get("clipped"))
    pp_reprojected = sum(1 for p in post_process_results if p.get("reprojected"))
    pp_failed = sum(1 for p in post_process_results if p.get("state") == "failed")

    status_label = (
        "completed"
        if imagery_failed == 0
        and downloads_failed == 0
        and downloads_succeeded == imagery_ready
        and pp_failed == 0
        else "partial_imagery"
    )
    result: dict[str, object] = {
        "status": status_label,
        "instance_id": instance_id,
        "blob_name": blob_name,
        "blob_url": blob_event.get("blob_url", ""),
        "feature_count": feature_count,
        "aoi_count": aoi_count,
        "metadata_count": metadata_count,
        "imagery_ready": imagery_ready,
        "imagery_failed": imagery_failed,
        "downloads_completed": downloads_completed,
        "post_process_completed": pp_completed,
        "post_process_clipped": pp_clipped,
        "post_process_reprojected": pp_reprojected,
        "imagery_outcomes": imagery_outcomes,
        "download_results": download_results,
        "post_process_results": post_process_results,
        "message": (
            f"Parsed {feature_count} feature(s), "
            f"prepared {aoi_count} AOI(s), "
            f"wrote {metadata_count} metadata record(s), "
            f"imagery ready={imagery_ready} failed={imagery_failed}, "
            f"downloaded={downloads_completed}, "
            f"clipped={pp_clipped} reprojected={pp_reprojected}."
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


# ---------------------------------------------------------------------------
# Polling sub-orchestration (M-2.3)
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
        - ``state``: ``"ready"`` | ``"failed"`` | ``"cancelled"`` | ``"acquisition_timeout"``
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

        # Poll via activity
        try:
            poll_result = yield context.call_activity(
                "poll_order",
                {"order_id": order_id, "provider": provider},
            )
            # Reset retry count on success
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

            # Exponential backoff: base * 2^(retry_count - 1)
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

        # Not terminal — sleep with a Durable timer (zero compute cost)
        fire_at = context.current_utc_datetime + timedelta(seconds=poll_interval)
        yield context.create_timer(fire_at)

    # Timeout
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

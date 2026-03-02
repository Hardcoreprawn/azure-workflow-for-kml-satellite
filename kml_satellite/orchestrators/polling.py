"""Polling orchestrator for long-running imagery orders.

Consolidated polling logic extracted from phases.py to support long-running
order-polling workflows. Uses timer-based waits for zero-cost asynchrony and
exponential backoff on transient errors.

References:
    PID FR-3.9  (Polling and backoff strategy)
    Issue #55   (Make polling stage concurrency-aware)
    Issue #104  (Extract polling and error helpers)
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

    import azure.durable_functions as df

logger = logging.getLogger("kml_satellite.orchestrators.polling")

# ---------------------------------------------------------------------------
# Polling configuration defaults (PID FR-3.9)
# ---------------------------------------------------------------------------

#: Seconds between poll attempts (default 30).
DEFAULT_POLL_INTERVAL_SECONDS = 30

#: Maximum total polling wait in seconds (default 1800 = 30 minutes).
DEFAULT_POLL_TIMEOUT_SECONDS = 1800

#: Maximum retry attempts on transient poll errors (default 3).
DEFAULT_MAX_RETRIES = 3

#: Exponential backoff base in seconds (default 5).
#: Backoff = 5 * 2^(retry_count-1) seconds
DEFAULT_RETRY_BASE_SECONDS = 5

#: Max concurrent polling sub-orchestrations per batch.
DEFAULT_POLL_BATCH_SIZE = 10


def poll_until_ready(
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
    polls.  Implements exponential backoff on transient errors and
    fails fast on non-retryable errors.

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
            retryable = bool(getattr(exc, "retryable", True))
            if not retryable:
                if not context.is_replaying:
                    logger.error(
                        "Non-retryable poll error | instance=%s | order=%s | "
                        "feature=%s | error=%s",
                        instance_id,
                        order_id,
                        feature_name,
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
                    "error": f"Non-retryable poll error: {exc}",
                }

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

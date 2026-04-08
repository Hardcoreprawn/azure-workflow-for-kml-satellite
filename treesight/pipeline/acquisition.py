"""Phase 2 — Acquisition logic (§3.2).

Pure business logic for imagery search, order, and polling.
"""

from __future__ import annotations

import time
from typing import Any

from treesight.config import config_get_int
from treesight.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    DEFAULT_RETRY_BASE_SECONDS,
    MAX_POLL_ITERATIONS,
)
from treesight.log import log_error, log_phase
from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters
from treesight.models.outcomes import ImageryOutcome
from treesight.providers.base import ImageryProvider


def acquire_imagery(
    aoi: AOI,
    provider: ImageryProvider,
    filters: ImageryFilters,
) -> dict[str, Any]:
    """Search for imagery and place an order for the best scene."""
    results = provider.search(aoi, filters)
    if not results:
        return ImageryOutcome(
            state="failed",
            provider=provider.name,
            aoi_feature_name=aoi.feature_name,
            error="No imagery found matching filters",
        ).model_dump()

    best = results[0]  # Provider returns best-match first
    order_id = provider.order(best.scene_id)

    log_phase(
        "acquisition",
        "order_placed",
        aoi_name=aoi.feature_name,
        scene_id=best.scene_id,
        order_id=order_id,
    )

    return ImageryOutcome(
        order_id=order_id,
        scene_id=best.scene_id,
        provider=provider.name,
        cloud_cover_pct=best.cloud_cover_pct,
        acquisition_date=best.acquisition_date.isoformat(),
        spatial_resolution_m=best.spatial_resolution_m,
        asset_url=best.asset_url,
        aoi_feature_name=aoi.feature_name,
    ).model_dump()


def acquire_composite(
    aoi: AOI,
    provider: ImageryProvider,
    filters: ImageryFilters,
    *,
    temporal_count: int = 6,
) -> list[dict[str, Any]]:
    """Search NAIP + Sentinel-2 and place orders for all results.

    Returns a list of order dicts, each tagged with
    ``role = "detail" | "temporal"`` in ``extra``.
    Uses ``composite_search`` on providers that support it.  Falls back to
    a single ``search`` call otherwise.
    """
    if hasattr(provider, "composite_search"):
        results = provider.composite_search(aoi, filters, temporal_count=temporal_count)  # type: ignore[attr-defined]
    else:
        results = provider.search(aoi, filters)

    if not results:
        return [
            ImageryOutcome(
                state="failed",
                provider=provider.name,
                aoi_feature_name=aoi.feature_name,
                error="No imagery found matching filters",
            ).model_dump()
        ]

    orders: list[dict[str, Any]] = []
    for r in results:
        order_id = provider.order(r.scene_id)
        role = r.extra.get("role", "temporal")
        collection = r.extra.get("collection", "")

        log_phase(
            "acquisition",
            "order_placed",
            aoi_name=aoi.feature_name,
            scene_id=r.scene_id,
            order_id=order_id,
            role=role,
            collection=collection,
        )

        orders.append(
            ImageryOutcome(
                order_id=order_id,
                scene_id=r.scene_id,
                provider=provider.name,
                cloud_cover_pct=r.cloud_cover_pct,
                acquisition_date=r.acquisition_date.isoformat(),
                spatial_resolution_m=r.spatial_resolution_m,
                asset_url=r.asset_url,
                aoi_feature_name=aoi.feature_name,
                role=role,
                collection=collection,
            ).model_dump()
        )

    return orders


def poll_order(
    order_id: str,
    provider: ImageryProvider,
    *,
    poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS,
    poll_timeout: int = DEFAULT_POLL_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_base: int = DEFAULT_RETRY_BASE_SECONDS,
) -> ImageryOutcome:
    """Poll a single order until terminal state or timeout."""
    start = time.monotonic()
    poll_count = 0
    retries = 0

    for _iteration in range(MAX_POLL_ITERATIONS):
        elapsed = time.monotonic() - start
        if elapsed >= poll_timeout:
            return ImageryOutcome(
                state="acquisition_timeout",
                order_id=order_id,
                provider=provider.name,
                poll_count=poll_count,
                elapsed_seconds=elapsed,
                error=f"Polling timed out after {elapsed:.0f}s",
            )

        try:
            status = provider.poll(order_id)
            poll_count += 1

            log_phase(
                "acquisition",
                "poll",
                order_id=order_id,
                state=status.state,
                poll_count=poll_count,
            )

            if status.is_terminal:
                return ImageryOutcome(
                    state=status.state,
                    order_id=order_id,
                    provider=provider.name,
                    poll_count=poll_count,
                    elapsed_seconds=time.monotonic() - start,
                )

        except Exception as exc:
            retries += 1
            if retries > max_retries:
                return ImageryOutcome(
                    state="failed",
                    order_id=order_id,
                    provider=provider.name,
                    poll_count=poll_count,
                    elapsed_seconds=time.monotonic() - start,
                    error=str(exc),
                )
            backoff = retry_base * (2 ** (retries - 1))
            log_error(
                "acquisition",
                "poll_retry",
                str(exc),
                retry=retries,
                backoff=backoff,
            )
            time.sleep(backoff)
            continue

        time.sleep(poll_interval)

    # Exhausted MAX_POLL_ITERATIONS without reaching timeout or terminal state
    return ImageryOutcome(
        state="acquisition_timeout",
        order_id=order_id,
        provider=provider.name,
        poll_count=poll_count,
        elapsed_seconds=time.monotonic() - start,
        error=f"Exceeded {MAX_POLL_ITERATIONS} poll iterations",
    )


def poll_orders_batch(
    orders: list[dict[str, Any]],
    provider: ImageryProvider,
    overrides: dict[str, Any] | None = None,
) -> list[ImageryOutcome]:
    """Poll a batch of orders sequentially (concurrency handled by orchestrator)."""
    overrides = overrides or {}
    results: list[ImageryOutcome] = []
    for order in orders:
        outcome = poll_order(
            order["order_id"],
            provider,
            poll_interval=config_get_int(
                overrides,
                "poll_interval_seconds",
                DEFAULT_POLL_INTERVAL_SECONDS,
            ),
            poll_timeout=config_get_int(
                overrides,
                "poll_timeout_seconds",
                DEFAULT_POLL_TIMEOUT_SECONDS,
            ),
            max_retries=config_get_int(
                overrides,
                "max_retries",
                DEFAULT_MAX_RETRIES,
            ),
            retry_base=config_get_int(
                overrides,
                "retry_base_seconds",
                DEFAULT_RETRY_BASE_SECONDS,
            ),
        )
        outcome.scene_id = order.get("scene_id", "")
        outcome.aoi_feature_name = order.get("aoi_feature_name", "")
        results.append(outcome)
    return results

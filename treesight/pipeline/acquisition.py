"""Phase 2 — Acquisition logic (§3.2).

Pure business logic for imagery search, order, and status polling.
"""

from __future__ import annotations

from typing import Any, TypeGuard, get_args

from treesight.log import log_phase
from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters
from treesight.models.outcomes import ImageryOutcome, ImageryOutcomeState
from treesight.providers.base import ImageryProvider


def _is_imagery_outcome_state(value: str) -> TypeGuard[ImageryOutcomeState]:
    """Return whether ``value`` is a valid ``ImageryOutcome.state`` literal."""
    return value in get_args(ImageryOutcomeState)


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


def check_order_status(
    order_id: str,
    provider: ImageryProvider,
) -> dict[str, Any]:
    """Single-shot status poll — no loop, no sleep.

    Returns a dict with ``state``, ``is_terminal``, ``order_id``, ``provider``,
    and an optional ``error`` field.  The orchestrator owns the retry / timer
    logic; this function makes exactly one provider call per invocation.
    """
    status = provider.poll(order_id)
    state: str = status.state
    error: str | None = None

    if status.is_terminal and not _is_imagery_outcome_state(state):
        error = f"Unsupported terminal state '{state}' from provider {provider.name}"
        state = "failed"
    elif status.is_terminal and state == "failed":
        error = getattr(status, "message", None)

    log_phase(
        "acquisition",
        "check_order_status",
        order_id=order_id,
        state=state,
        is_terminal=status.is_terminal,
    )

    return {
        "state": state,
        "is_terminal": status.is_terminal,
        "order_id": order_id,
        "provider": provider.name,
        "error": error,
    }

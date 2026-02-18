"""Acquire imagery activity — search, select, and order satellite imagery.

This activity takes a processed AOI, queries the configured imagery
provider's catalogue, selects the best matching scene, and submits an
order.  It does **not** poll or download — those are handled by the
orchestrator's timer-based polling loop and the ``download_imagery``
activity (M-2.4).

The function returns enough information for the orchestrator to drive
the poll/download cycle: ``order_id``, ``scene_id``, and ``provider``.

Engineering standards:
    PID 7.4.1  Zero-Assumption Input Handling — validate AOI and filters.
    PID 7.4.2  Fail Loudly — ``ProviderSearchError`` / ``ProviderOrderError``
               propagate to the orchestrator for retry / dead-letter.
    PID 7.4.4  Idempotent — same AOI + filters → same best scene selection
               (deterministic sort by cloud cover ascending).
    PID 7.4.5  Explicit — typed models, named constants, no magic strings.
    PID 7.4.6  Observability — structured logging at activity boundaries.

References:
    PID FR-3.8  (submit search queries to provider API)
    PID FR-3.9  (poll asynchronous job status)
    PID FR-5.3  (Durable Functions for imagery acquisition)
    PID Section 7.2  (Orchestration Pattern — Fan-Out per Polygon)
"""

from __future__ import annotations

import logging
from typing import Any

from kml_satellite.models.aoi import AOI
from kml_satellite.models.imagery import ImageryFilters, ProviderConfig
from kml_satellite.providers.base import ProviderError
from kml_satellite.providers.factory import get_provider

logger = logging.getLogger("kml_satellite.activities.acquire_imagery")


class ImageryAcquisitionError(Exception):
    """Raised when imagery acquisition fails.

    Attributes:
        message: Human-readable error description.
        retryable: Whether the orchestrator should retry the operation.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        self.message = message
        self.retryable = retryable
        super().__init__(message)


def acquire_imagery(
    aoi_dict: dict[str, Any],
    *,
    provider_name: str = "planetary_computer",
    provider_config: dict[str, Any] | None = None,
    filters_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Search for imagery, select the best scene, and submit an order.

    Args:
        aoi_dict: Serialised AOI dict from the ``prepare_aoi`` activity.
        provider_name: Name of the imagery provider to use.
        provider_config: Optional provider configuration overrides.
        filters_dict: Optional imagery filter overrides.

    Returns:
        A dict containing:
        - ``order_id``: Provider-specific order identifier.
        - ``scene_id``: The selected scene identifier.
        - ``provider``: Provider name.
        - ``cloud_cover_pct``: Cloud cover of the selected scene.
        - ``acquisition_date``: ISO 8601 acquisition date string.
        - ``spatial_resolution_m``: Ground sample distance in metres.
        - ``asset_url``: Direct asset URL (if available).
        - ``aoi_feature_name``: Name of the AOI being processed.

    Raises:
        ImageryAcquisitionError: If no imagery is found or ordering fails.
    """
    # Deserialise AOI (PID 7.4.1 — validate input)
    try:
        aoi = AOI.from_dict(aoi_dict)
    except (TypeError, KeyError, ValueError) as exc:
        msg = f"Invalid AOI payload: {exc}"
        raise ImageryAcquisitionError(msg, retryable=False) from exc

    logger.info(
        "acquire_imagery started | feature=%s | provider=%s",
        aoi.feature_name,
        provider_name,
    )

    # Build provider config
    config = _build_provider_config(provider_name, provider_config)

    # Build imagery filters
    filters = _build_filters(filters_dict)

    # Get provider adapter
    try:
        provider = get_provider(provider_name, config)
    except ProviderError as exc:
        msg = f"Failed to create provider {provider_name!r}: {exc}"
        raise ImageryAcquisitionError(msg, retryable=False) from exc

    # Search
    try:
        results = provider.search(aoi, filters)
    except ProviderError as exc:
        msg = f"Imagery search failed for {aoi.feature_name!r}: {exc}"
        raise ImageryAcquisitionError(msg, retryable=exc.retryable) from exc

    if not results:
        msg = f"No imagery found for {aoi.feature_name!r} with provider {provider_name!r}"
        logger.warning(msg)
        raise ImageryAcquisitionError(msg, retryable=False)

    # Select best scene (first result — already sorted by cloud cover ascending)
    best = results[0]

    logger.info(
        "Best scene selected | feature=%s | scene=%s | cloud=%.1f%% | resolution=%.1fm",
        aoi.feature_name,
        best.scene_id,
        best.cloud_cover_pct,
        best.spatial_resolution_m,
    )

    # Order
    try:
        order = provider.order(best.scene_id)
    except ProviderError as exc:
        msg = f"Order failed for scene {best.scene_id!r}: {exc}"
        raise ImageryAcquisitionError(msg, retryable=exc.retryable) from exc

    logger.info(
        "Order submitted | feature=%s | order_id=%s | scene=%s | provider=%s",
        aoi.feature_name,
        order.order_id,
        order.scene_id,
        order.provider,
    )

    return {
        "order_id": order.order_id,
        "scene_id": order.scene_id,
        "provider": order.provider,
        "cloud_cover_pct": best.cloud_cover_pct,
        "acquisition_date": best.acquisition_date.isoformat(),
        "spatial_resolution_m": best.spatial_resolution_m,
        "asset_url": best.asset_url,
        "aoi_feature_name": aoi.feature_name,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_provider_config(
    provider_name: str,
    overrides: dict[str, Any] | None,
) -> ProviderConfig:
    """Build a ``ProviderConfig`` from the provider name and optional overrides."""
    if overrides is None:
        return ProviderConfig(name=provider_name)

    return ProviderConfig(
        name=provider_name,
        api_base_url=str(overrides.get("api_base_url", "")),
        auth_mechanism=str(overrides.get("auth_mechanism", "none")),
        keyvault_secret_name=str(overrides.get("keyvault_secret_name", "")),
        extra_params={str(k): str(v) for k, v in overrides.get("extra_params", {}).items()},
    )


def _build_filters(
    overrides: dict[str, Any] | None,
) -> ImageryFilters:
    """Build ``ImageryFilters`` from an optional overrides dict.

    Returns default filters if *overrides* is ``None``.
    """
    if overrides is None:
        return ImageryFilters()

    from datetime import datetime

    date_start = overrides.get("date_start")
    date_end = overrides.get("date_end")

    if isinstance(date_start, str):
        date_start = datetime.fromisoformat(date_start)
    if isinstance(date_end, str):
        date_end = datetime.fromisoformat(date_end)

    return ImageryFilters(
        max_cloud_cover_pct=float(overrides.get("max_cloud_cover_pct", 20.0)),
        max_off_nadir_deg=float(overrides.get("max_off_nadir_deg", 30.0)),
        min_resolution_m=float(overrides.get("min_resolution_m", 0.0)),
        max_resolution_m=float(overrides.get("max_resolution_m", 50.0)),
        date_start=date_start,
        date_end=date_end,
        collections=list(overrides.get("collections", [])),
    )

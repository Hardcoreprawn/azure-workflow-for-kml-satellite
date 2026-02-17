"""Poll order activity — check the status of an imagery order.

This activity is called by the orchestrator's timer-based polling loop.
It queries the provider adapter for the current order status and returns
a serialisable result the orchestrator uses to decide whether to continue
polling, proceed to download, or flag an error.

Engineering standards:
    PID 7.4.1  Zero-Assumption Input Handling — validate order payload.
    PID 7.4.2  Fail Loudly — provider errors propagate with ``retryable`` flag.
    PID 7.4.5  Explicit — typed models, named constants.
    PID 7.4.6  Observability — structured logging with correlation context.

References:
    PID FR-3.9  (poll asynchronous job status until completion)
    PID FR-5.3  (Durable Functions for long-running workflows)
    PID FR-6.4  (retry with exponential backoff)
"""

from __future__ import annotations

import logging
from typing import Any

from kml_satellite.models.imagery import OrderState, ProviderConfig
from kml_satellite.providers.base import ProviderError
from kml_satellite.providers.factory import get_provider

logger = logging.getLogger("kml_satellite.activities.poll_order")


class PollError(Exception):
    """Raised when order polling fails.

    Attributes:
        message: Human-readable error description.
        retryable: Whether the orchestrator should retry.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        self.message = message
        self.retryable = retryable
        super().__init__(message)


def poll_order(
    order_payload: dict[str, Any],
    *,
    provider_name: str | None = None,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check the current status of an imagery order.

    Args:
        order_payload: Dict containing at least ``order_id`` and ``provider``.
        provider_name: Override for the provider name (defaults to
            ``order_payload["provider"]``).
        provider_config: Optional provider configuration overrides.

    Returns:
        A dict containing:
        - ``order_id``: The order being polled.
        - ``state``: Current state string (``"pending"``, ``"ready"``,
          ``"failed"``, ``"cancelled"``).
        - ``message``: Human-readable status message.
        - ``progress_pct``: Estimated completion percentage (0-100).
        - ``is_terminal``: Whether this state is final (ready/failed/cancelled).

    Raises:
        PollError: If polling fails.
    """
    order_id = str(order_payload.get("order_id", ""))
    if not order_id:
        msg = "poll_order: order_id is missing from payload"
        raise PollError(msg, retryable=False)

    prov_name = provider_name or str(order_payload.get("provider", ""))
    if not prov_name:
        msg = "poll_order: provider name is missing"
        raise PollError(msg, retryable=False)

    logger.info(
        "poll_order started | order_id=%s | provider=%s",
        order_id,
        prov_name,
    )

    # Build provider
    config = ProviderConfig(name=prov_name)
    if provider_config:
        config = ProviderConfig(
            name=prov_name,
            api_base_url=str(provider_config.get("api_base_url", "")),
            auth_mechanism=str(provider_config.get("auth_mechanism", "none")),
            keyvault_secret_name=str(provider_config.get("keyvault_secret_name", "")),
            extra_params={
                str(k): str(v) for k, v in provider_config.get("extra_params", {}).items()
            },
        )

    try:
        provider = get_provider(prov_name, config)
    except ProviderError as exc:
        msg = f"Failed to create provider {prov_name!r}: {exc}"
        raise PollError(msg, retryable=False) from exc

    try:
        status = provider.poll(order_id)
    except ProviderError as exc:
        msg = f"Poll failed for order {order_id!r}: {exc}"
        raise PollError(msg, retryable=exc.retryable) from exc

    is_terminal = status.state in (
        OrderState.READY,
        OrderState.FAILED,
        OrderState.CANCELLED,
    )

    logger.info(
        "poll_order completed | order_id=%s | state=%s | progress=%.0f%% | terminal=%s",
        order_id,
        status.state.value,
        status.progress_pct,
        is_terminal,
    )

    return {
        "order_id": status.order_id,
        "state": status.state.value,
        "message": status.message,
        "progress_pct": status.progress_pct,
        "is_terminal": is_terminal,
    }

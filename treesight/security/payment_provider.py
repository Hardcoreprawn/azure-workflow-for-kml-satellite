"""Payment provider abstraction — pluggable billing backend.

The billing ledger records runs internally.  When a billable event occurs
(overage completion, refund), it delegates to a ``PaymentProvider``.
Stripe is one implementation; others can be swapped in without touching
the ledger.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class PaymentProvider(Protocol):
    """Minimal interface for a payment/billing backend."""

    def report_usage(
        self,
        *,
        user_id: str,
        subscription_item_id: str,
        quantity: int,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        """Report metered usage (e.g. overage runs).

        Parameters
        ----------
        subscription_item_id:
            Stripe subscription *item* ID (``si_...``), not the subscription
            ID (``sub_...``).

        Returns an external record ID (e.g. Stripe UsageRecord ID) or None.
        """
        return None

    def credit_usage(
        self,
        *,
        user_id: str,
        subscription_item_id: str,
        quantity: int,
        idempotency_key: str,
        reason: str = "",
    ) -> str | None:
        """Credit/refund metered usage (e.g. failed overage run).

        Sends a negative usage record to reverse a previous charge.

        Returns an external record ID or None.
        """
        return None


class NullProvider:
    """No-op provider for free tiers, tests, and when billing is unconfigured."""

    def report_usage(
        self,
        *,
        user_id: str,
        subscription_item_id: str,
        quantity: int,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        logger.debug(
            "NullProvider.report_usage user=%s qty=%d key=%s",
            user_id,
            quantity,
            idempotency_key,
        )
        return None

    def credit_usage(
        self,
        *,
        user_id: str,
        subscription_item_id: str,
        quantity: int,
        idempotency_key: str,
        reason: str = "",
    ) -> str | None:
        logger.debug(
            "NullProvider.credit_usage user=%s qty=%d key=%s reason=%s",
            user_id,
            quantity,
            idempotency_key,
            reason,
        )
        return None


class StripeProvider:
    """Stripe metered billing provider.

    Reports overage usage via Stripe Usage Records on metered subscription
    items.  Credits are reported as negative usage records.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _get_stripe(self) -> Any:
        import stripe

        stripe.api_key = self._api_key
        return stripe

    def report_usage(
        self,
        *,
        user_id: str,
        subscription_item_id: str,
        quantity: int,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        stripe = self._get_stripe()
        try:
            record = stripe.SubscriptionItem.create_usage_record(
                subscription_item_id,
                quantity=quantity,
                action="increment",
                idempotency_key=idempotency_key,
            )
            logger.info(
                "Stripe usage reported user=%s qty=%d record=%s",
                user_id,
                quantity,
                record.id,
            )
            return record.id
        except Exception:
            logger.exception(
                "Stripe usage report failed user=%s qty=%d",
                user_id,
                quantity,
            )
            return None

    def credit_usage(
        self,
        *,
        user_id: str,
        subscription_item_id: str,
        quantity: int,
        idempotency_key: str,
        reason: str = "",
    ) -> str | None:
        stripe = self._get_stripe()
        try:
            record = stripe.SubscriptionItem.create_usage_record(
                subscription_item_id,
                quantity=-abs(quantity),
                action="increment",
                idempotency_key=idempotency_key,
            )
            logger.info(
                "Stripe credit reported user=%s qty=%d reason=%s record=%s",
                user_id,
                quantity,
                reason,
                record.id,
            )
            return record.id
        except Exception:
            logger.exception(
                "Stripe credit failed user=%s qty=%d reason=%s",
                user_id,
                quantity,
                reason,
            )
            return None


_provider: PaymentProvider | None = None


def get_payment_provider() -> PaymentProvider:
    """Return the configured payment provider (singleton)."""
    global _provider
    if _provider is not None:
        return _provider

    from treesight.config import STRIPE_API_KEY

    if STRIPE_API_KEY:
        _provider = StripeProvider(STRIPE_API_KEY)
        logger.info("Payment provider: Stripe")
    else:
        _provider = NullProvider()
        logger.info("Payment provider: Null (no STRIPE_API_KEY)")
    return _provider


def set_payment_provider(provider: PaymentProvider | None) -> None:
    """Override the cached payment provider.

    Pass ``None`` to reset the singleton so the next
    ``get_payment_provider()`` call reloads from configuration.
    """
    global _provider
    _provider = provider

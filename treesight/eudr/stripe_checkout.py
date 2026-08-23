"""Stripe Checkout session helpers for EUDR subscription.

Pure construction logic: builds the session kwargs dict from validated
inputs.  No HTTP or Azure Functions dependency.
"""

from __future__ import annotations

from treesight.config import (
    STRIPE_PRICE_ID_EUDR_BASE_EUR,
    STRIPE_PRICE_ID_EUDR_BASE_GBP,
    STRIPE_PRICE_ID_EUDR_BASE_USD,
    STRIPE_PRICE_ID_EUDR_METERED_EUR,
    STRIPE_PRICE_ID_EUDR_METERED_GBP,
    STRIPE_PRICE_ID_EUDR_METERED_USD,
)

_BASE_PRICES = {
    "GBP": STRIPE_PRICE_ID_EUDR_BASE_GBP,
    "USD": STRIPE_PRICE_ID_EUDR_BASE_USD,
    "EUR": STRIPE_PRICE_ID_EUDR_BASE_EUR,
}
_METERED_PRICES = {
    "GBP": STRIPE_PRICE_ID_EUDR_METERED_GBP,
    "USD": STRIPE_PRICE_ID_EUDR_METERED_USD,
    "EUR": STRIPE_PRICE_ID_EUDR_METERED_EUR,
}


def resolve_eudr_prices(currency: str) -> tuple[str | None, str | None]:
    """Return ``(base_price_id, metered_price_id)`` for *currency*, or ``(None, None)``."""
    return _BASE_PRICES.get(currency), _METERED_PRICES.get(currency)


def build_eudr_checkout_kwargs(
    *,
    user_id: str,
    org_id: str,
    base_price: str,
    metered_price: str,
    origin: str,
    currency: str,
) -> dict:
    """Return keyword arguments for ``stripe.checkout.Session.create``.

    All arguments are pre-validated by the caller.
    """
    return {
        "mode": "subscription",
        "line_items": [
            {"price": base_price, "quantity": 1},
            {"price": metered_price},
        ],
        "success_url": f"{origin}/eudr/?subscribed=true",
        "cancel_url": f"{origin}/eudr/?billing=cancel",
        "client_reference_id": user_id,
        "metadata": {
            "user_id": user_id,
            "org_id": org_id,
            "product": "eudr",
            "currency": currency,
        },
        "subscription_data": {
            "metadata": {
                "user_id": user_id,
                "org_id": org_id,
                "product": "eudr",
                "currency": currency,
            }
        },
        "billing_address_collection": "required",
        "automatic_tax": {"enabled": True},
        "consent_collection": {"terms_of_service": "required"},
        "custom_text": {
            "terms_of_service_acceptance": {
                "message": (
                    "I agree to the [Terms of Service]"
                    f"({origin}/terms.html)"
                    " and acknowledge my right to cancel within"
                    " 14 days under the Consumer Contracts"
                    " Regulations 2013."
                )
            }
        },
        "allow_promotion_codes": True,
    }

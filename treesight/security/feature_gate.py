"""Feature gating for billing and other premium features.

While Stripe is in test mode, billing is restricted to an explicit allow-list
of user IDs set via the ``BILLING_ALLOWED_USERS`` environment variable.
Users not on the list see demo-tier pricing and a "contact us" prompt instead
of the checkout flow.
"""

from __future__ import annotations

import logging

from treesight.config import BILLING_ALLOWED_USERS

logger = logging.getLogger(__name__)


def billing_allowed(user_id: str | None) -> bool:
    """Return True if *user_id* is permitted to use real billing.

    Rules:
    - If the allow-list is empty, billing is gated for everyone.
    - Anonymous users are always gated.
    - Users whose ID appears in ``BILLING_ALLOWED_USERS`` are allowed.
    """
    if not user_id or user_id == "anonymous":
        return False
    if not BILLING_ALLOWED_USERS:
        return False
    return user_id in BILLING_ALLOWED_USERS


# Relative price indicators shown when billing is gated.
GATED_PRICE_LABELS: dict[str, str] = {
    "demo": "Free",
    "free": "Free",
    "starter": "$",
    "pro": "$$",
    "team": "$$$",
    "enterprise": "Price on Enquiry",
}

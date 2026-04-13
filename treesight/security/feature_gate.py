"""Feature gating for billing and other premium features.

Operator status is checked in two places (either granting access is sufficient):
1. ``BILLING_ALLOWED_USERS`` environment variable — static allow-list (fast, no I/O)
2. Cosmos ``users`` container — ``billing_allowed`` flag per user (fallback)
"""

from __future__ import annotations

import logging

from treesight.config import BILLING_ALLOWED_USERS

logger = logging.getLogger(__name__)


def billing_allowed(user_id: str | None) -> bool:
    """Return True if *user_id* is permitted to use real billing.

    Rules:
    - Anonymous users are always gated.
    - Users with ``billing_allowed: true`` in Cosmos are allowed.
    - Users in the ``BILLING_ALLOWED_USERS`` env-var allow-list are allowed.
    - Otherwise gated.
    """
    if not user_id or user_id == "anonymous":
        return False

    # Fast path: static env-var list (no I/O)
    if BILLING_ALLOWED_USERS and user_id in BILLING_ALLOWED_USERS:
        return True

    # Check Cosmos user record
    try:
        from treesight.security.users import is_billing_allowed

        if is_billing_allowed(user_id):
            return True
    except Exception:
        logger.debug("Cosmos billing_allowed check failed for user=%s", user_id, exc_info=True)

    return False


# Relative price indicators shown when billing is gated.
GATED_PRICE_LABELS: dict[str, str] = {
    "demo": "Free",
    "free": "Free",
    "starter": "$",
    "pro": "$$",
    "team": "$$$",
    "enterprise": "Price on Enquiry",
}

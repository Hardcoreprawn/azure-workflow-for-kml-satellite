"""EUDR per-parcel metered billing (#613).

Org-scoped billing for EUDR compliance assessments:
- 2 lifetime free assessments per org (no card required)
- £49/month base subscription + £3/parcel metered overage
- Graduated tiers: 100+ £2.50, 500+ £1.80
- Only org owners can subscribe

All state lives on the org document in the ``billing`` sub-dict.
"""

from __future__ import annotations

import logging
from typing import Any

from treesight.constants import EUDR_FREE_ASSESSMENTS, EUDR_INCLUDED_PARCELS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Free trial
# ---------------------------------------------------------------------------


def get_eudr_trial_remaining(org_id: str) -> int:
    """Return how many free EUDR assessments this org has left."""
    from treesight.security.orgs import get_org

    org = get_org(org_id)
    if not org:
        return 0
    used = org.get("eudr_assessments_used", 0)
    return max(EUDR_FREE_ASSESSMENTS - used, 0)


def consume_eudr_trial(org_id: str) -> None:
    """Consume one free EUDR trial assessment for the org.

    Raises ValueError if the org doesn't exist or the trial is exhausted.
    """
    from treesight.security.orgs import get_org
    from treesight.storage.cosmos import upsert_item

    org = get_org(org_id)
    if not org:
        raise ValueError(f"Org {org_id} not found")

    used = org.get("eudr_assessments_used", 0)
    if used >= EUDR_FREE_ASSESSMENTS:
        raise ValueError(f"Org {org_id} free trial exhausted ({used}/{EUDR_FREE_ASSESSMENTS})")

    org["eudr_assessments_used"] = used + 1
    upsert_item("orgs", org)
    logger.info("EUDR trial consumed org=%s used=%d", org_id, used + 1)


# ---------------------------------------------------------------------------
# Entitlement check
# ---------------------------------------------------------------------------


def check_eudr_entitlement(org_id: str) -> dict[str, Any]:
    """Check whether an org can submit an EUDR assessment.

    Returns a dict with ``allowed`` (bool) and ``reason`` (str).
    """
    from treesight.security.orgs import get_org

    org = get_org(org_id)
    if not org:
        return {"allowed": False, "reason": "org_not_found"}

    # Check active subscription first
    billing = org.get("billing", {})
    if billing.get("eudr_status") == "active" and billing.get("eudr_tier") == "eudr_pro":
        return {"allowed": True, "reason": "subscription"}

    # Fall back to free trial
    used = org.get("eudr_assessments_used", 0)
    if used < EUDR_FREE_ASSESSMENTS:
        return {"allowed": True, "reason": "free_trial"}

    return {"allowed": False, "reason": "subscription_required"}


# ---------------------------------------------------------------------------
# Billing status
# ---------------------------------------------------------------------------


def get_eudr_billing_status(org_id: str) -> dict[str, Any]:
    """Return EUDR billing status for the frontend."""
    from treesight.security.orgs import get_org

    org = get_org(org_id)
    if not org:
        return {
            "plan": "none",
            "subscribed": False,
            "assessments_used": 0,
            "trial_remaining": 0,
            "period_parcels_used": 0,
            "included_parcels": EUDR_INCLUDED_PARCELS,
            "overage_parcels": 0,
        }

    billing = org.get("billing", {})
    used = org.get("eudr_assessments_used", 0)
    subscribed = billing.get("eudr_status") == "active" and billing.get("eudr_tier") == "eudr_pro"
    period_parcels = billing.get("eudr_period_parcels", 0) if subscribed else 0
    overage = max(period_parcels - EUDR_INCLUDED_PARCELS, 0) if subscribed else 0

    return {
        "plan": "eudr_pro" if subscribed else "free_trial",
        "subscribed": subscribed,
        "assessments_used": used,
        "trial_remaining": max(EUDR_FREE_ASSESSMENTS - used, 0),
        "period_parcels_used": period_parcels,
        "included_parcels": EUDR_INCLUDED_PARCELS,
        "overage_parcels": overage,
        "stripe_customer_id": billing.get("stripe_customer_id"),
    }


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------


def save_eudr_subscription(
    org_id: str,
    *,
    tier: str,
    status: str,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    stripe_subscription_item_id: str | None = None,
) -> None:
    """Persist EUDR subscription state on the org document."""
    from treesight.security.orgs import get_org
    from treesight.storage.cosmos import upsert_item

    org = get_org(org_id)
    if not org:
        raise ValueError(f"Org {org_id} not found")

    billing = org.get("billing", {})
    billing["eudr_tier"] = tier
    billing["eudr_status"] = status
    if stripe_customer_id:
        billing["stripe_customer_id"] = stripe_customer_id
    if stripe_subscription_id:
        billing["stripe_subscription_id"] = stripe_subscription_id
    if stripe_subscription_item_id:
        billing["stripe_subscription_item_id"] = stripe_subscription_item_id
    org["billing"] = billing
    upsert_item("orgs", org)
    logger.info(
        "EUDR subscription saved org=%s tier=%s status=%s",
        org_id,
        tier,
        status,
    )


# ---------------------------------------------------------------------------
# Usage recording
# ---------------------------------------------------------------------------


def record_eudr_usage(org_id: str, *, parcel_count: int) -> None:
    """Record parcel usage after successful assessment completion.

    Increments the lifetime counter and, for subscribed orgs, the period
    parcel counter.
    """
    from treesight.security.orgs import get_org
    from treesight.storage.cosmos import upsert_item

    org = get_org(org_id)
    if not org:
        raise ValueError(f"Org {org_id} not found")

    # Always increment lifetime counter
    org["eudr_assessments_used"] = org.get("eudr_assessments_used", 0) + parcel_count

    # Increment period parcels only for subscribed orgs
    billing = org.get("billing", {})
    if billing.get("eudr_status") == "active":
        billing["eudr_period_parcels"] = billing.get("eudr_period_parcels", 0) + parcel_count
        org["billing"] = billing

    upsert_item("orgs", org)
    logger.info(
        "EUDR usage recorded org=%s parcels=%d lifetime=%d",
        org_id,
        parcel_count,
        org["eudr_assessments_used"],
    )


# ---------------------------------------------------------------------------
# Stripe usage reporting
# ---------------------------------------------------------------------------


def report_eudr_stripe_usage(
    org_id: str,
    *,
    parcel_count: int,
    idempotency_key: str,
) -> str | None:
    """Report metered parcel usage to Stripe.

    Returns the Stripe UsageRecord ID, or None if reporting was skipped
    (e.g. free trial, no subscription item).
    """
    from treesight.security.orgs import get_org

    org = get_org(org_id)
    if not org:
        return None

    billing = org.get("billing", {})
    sub_item_id = billing.get("stripe_subscription_item_id")
    if not sub_item_id or billing.get("eudr_status") != "active":
        return None

    from treesight.security.payment_provider import get_payment_provider

    provider = get_payment_provider()
    return provider.report_usage(
        user_id=org_id,
        subscription_item_id=sub_item_id,
        quantity=parcel_count,
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# Owner check
# ---------------------------------------------------------------------------


def is_org_owner(org_id: str, user_id: str) -> bool:
    """Return True if user_id is an owner of the org."""
    from treesight.security.orgs import get_org

    org = get_org(org_id)
    if not org:
        return False
    members = org.get("members", [])
    return any(m["user_id"] == user_id and m.get("role") == "owner" for m in members)

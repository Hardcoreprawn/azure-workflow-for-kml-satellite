"""Billing ledger — run-level billing classification and lifecycle (#589).

Every pipeline run gets billing metadata written at submission and updated
on completion or failure.  The billing fields live on the ``RunRecord``
document in the Cosmos ``runs`` container.

The ledger is **provider-agnostic**: it calls the configured
``PaymentProvider`` for overage reporting/crediting.  Stripe is one
implementation; ``NullProvider`` is used when billing is unconfigured.
"""

from __future__ import annotations

import logging
from typing import Any

from treesight.security.redact import redact_user_id as _redact

logger = logging.getLogger(__name__)

_KNOWN_BILLING_TYPES = frozenset({"demo", "free", "included", "overage"})


def _safe_billing_type(value: object) -> str:
    """Return *value* only if it is a known billing type, else ``'unknown'``."""
    return str(value) if value in _KNOWN_BILLING_TYPES else "unknown"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify_run(tier: str, runs_used: int, included_limit: int) -> dict[str, Any]:
    """Classify a run as included, overage, free, or demo.

    Parameters
    ----------
    tier:
        The normalised subscription tier at submission time.
    runs_used:
        Number of runs already consumed *before* this one.
    included_limit:
        The ``run_limit`` for the tier (included runs per period).

    Returns
    -------
    dict with ``billing_type`` and ``overage_unit_price``.
    """
    from treesight.security.billing import PLAN_CATALOG, normalize_tier

    tier = normalize_tier(tier)
    plan = PLAN_CATALOG.get(tier, PLAN_CATALOG["free"])

    if tier == "demo":
        return {"billing_type": "demo", "overage_unit_price": None}
    if tier == "free":
        return {"billing_type": "free", "overage_unit_price": None}

    if runs_used < included_limit:
        return {"billing_type": "included", "overage_unit_price": None}

    rate = plan.get("overage_rate")
    return {"billing_type": "overage", "overage_unit_price": rate}


# ---------------------------------------------------------------------------
# Lifecycle helpers — called by submission / orchestrator
# ---------------------------------------------------------------------------


def billing_fields_for_submission(user_id: str) -> dict[str, Any]:
    """Return billing fields to embed in a ``RunRecord`` at submission time.

    Reads the user's effective subscription and current usage to classify the
    run.  Returns a dict suitable for unpacking into the ``RunRecord``
    constructor.
    """
    from treesight.security.billing import get_effective_subscription, normalize_tier
    from treesight.security.quota import get_usage

    sub = get_effective_subscription(user_id)
    tier = normalize_tier(sub.get("tier"))
    usage = get_usage(user_id)
    # usage["used"] already includes the current run (consume_quota was called first)
    # so the run *before* this one is used - 1
    used_before = max(usage["used"] - 1, 0)

    classification = classify_run(tier, used_before, usage["limit"])

    return {
        "tier_at_submission": tier,
        "billing_type": classification["billing_type"],
        "overage_unit_price": classification["overage_unit_price"],
        "billing_status": "pending",
    }


def complete_run_billing(user_id: str, instance_id: str) -> None:
    """Mark a run as successfully completed in the billing ledger.

    For overage runs, reports usage to the configured ``PaymentProvider``.
    """
    from treesight.storage.cosmos import read_item, upsert_item

    doc = read_item("runs", instance_id, user_id)
    if not doc:
        logger.warning(
            "No run document found for billing completion instance=%s user=%s",
            instance_id,
            _redact(user_id),
        )
        return

    billing_type = doc.get("billing_type")
    already_charged = doc.get("billing_status") == "charged"
    has_payment_ref = bool(doc.get("payment_ref"))
    if already_charged and (billing_type != "overage" or has_payment_ref):
        logger.info(
            "Run already charged instance=%s — skipping",
            instance_id,
        )
        return

    if billing_type == "overage":
        _report_overage(user_id, instance_id, doc)
        if not doc.get("payment_ref"):
            # Stay pending so Durable retry can re-attempt billing
            raise RuntimeError(
                f"Overage billing not confirmed instance={instance_id} user={_redact(user_id)}"
            )

    doc["billing_status"] = "charged"
    upsert_item("runs", doc)

    logger.info(
        "Billing completed instance=%s user=%s type=%s",
        instance_id,
        _redact(user_id),
        _safe_billing_type(billing_type),
    )


def fail_run_billing(
    user_id: str,
    instance_id: str,
    *,
    reason: str = "pipeline_failure",
) -> None:
    """Mark a run as failed/refunded in the billing ledger.

    For overage runs that were already reported, credits the payment provider.
    """
    from treesight.storage.cosmos import read_item, upsert_item

    doc = read_item("runs", instance_id, user_id)
    if not doc:
        logger.warning(
            "No run document found for billing failure instance=%s user=%s",
            instance_id,
            _redact(user_id),
        )
        return

    previous_status = doc.get("billing_status")
    if previous_status == "refunded":
        logger.info(
            "Run already refunded instance=%s — skipping",
            instance_id,
        )
        return

    # If it was an overage run that was already charged, credit first
    needs_credit = doc.get("billing_type") == "overage" and previous_status == "charged"

    if needs_credit:
        # Write interim status so a crash between credit and final update
        # is retryable — the run won't appear as "refunded" without credit.
        doc["billing_status"] = "credit_pending"
        doc["refund_reason"] = reason
        upsert_item("runs", doc)

        _credit_overage(user_id, instance_id, doc, reason)

        if not doc.get("payment_ref"):
            raise RuntimeError(
                f"Overage credit not confirmed instance={instance_id} user={_redact(user_id)}"
            )

    doc["billing_status"] = "refunded"
    doc["refund_reason"] = reason
    upsert_item("runs", doc)

    logger.info(
        "Billing refunded instance=%s user=%s reason=%s",
        instance_id,
        _redact(user_id),
        reason,
    )


# ---------------------------------------------------------------------------
# Payment provider integration
# ---------------------------------------------------------------------------


def _report_overage(user_id: str, instance_id: str, doc: dict[str, Any]) -> None:
    """Report overage usage to the payment provider."""
    from treesight.security.billing import get_effective_subscription
    from treesight.security.payment_provider import get_payment_provider

    sub = get_effective_subscription(user_id)
    stripe_si_id = sub.get("stripe_subscription_item_id", "")
    if not stripe_si_id:
        logger.info(
            "No Stripe subscription item for overage reporting user=%s instance=%s",
            _redact(user_id),
            instance_id,
        )
        return

    provider = get_payment_provider()
    ref = provider.report_usage(
        user_id=user_id,
        subscription_item_id=stripe_si_id,
        quantity=1,
        idempotency_key=f"overage-{instance_id}",
        metadata={"instance_id": instance_id, "tier": doc.get("tier_at_submission", "")},
    )
    if ref:
        from treesight.storage.cosmos import upsert_item

        doc["payment_ref"] = ref
        upsert_item("runs", doc)


def _credit_overage(user_id: str, instance_id: str, doc: dict[str, Any], reason: str) -> None:
    """Credit overage usage back via the payment provider."""
    from treesight.security.billing import get_effective_subscription
    from treesight.security.payment_provider import get_payment_provider

    sub = get_effective_subscription(user_id)
    stripe_si_id = sub.get("stripe_subscription_item_id", "")
    if not stripe_si_id:
        return

    provider = get_payment_provider()
    ref = provider.credit_usage(
        user_id=user_id,
        subscription_item_id=stripe_si_id,
        quantity=1,
        idempotency_key=f"credit-{instance_id}",
        reason=reason,
    )
    if ref:
        from treesight.storage.cosmos import upsert_item

        doc["payment_ref"] = ref
        upsert_item("runs", doc)

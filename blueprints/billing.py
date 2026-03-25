"""Billing blueprint — Stripe Checkout, webhooks, and subscription status.

UK compliance: Stripe Tax handles VAT, customer portal handles self-service
cancellation (Consumer Contracts Regulations 2013 — 14-day cooling-off).
"""

import json
import logging

import azure.functions as func

from blueprints._helpers import cors_headers, cors_preflight, error_response, require_auth
from treesight.config import (
    STRIPE_API_KEY,
    STRIPE_PRICE_ID_PRO_EUR,
    STRIPE_PRICE_ID_PRO_GBP,
    STRIPE_PRICE_ID_PRO_USD,
    STRIPE_WEBHOOK_SECRET,
)

logger = logging.getLogger(__name__)

bp = func.Blueprint()


def _stripe_configured() -> bool:
    return bool(STRIPE_API_KEY and STRIPE_WEBHOOK_SECRET)


def _get_stripe():
    """Lazily import and configure Stripe SDK."""
    import stripe

    stripe.api_key = STRIPE_API_KEY
    return stripe


def _safe_origin(req: func.HttpRequest) -> str:
    """Return the request Origin only if it's in our allowed set."""
    from blueprints._helpers import _ALLOWED_ORIGINS

    origin = req.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        return origin
    # Fall back to the first production origin in the allowlist
    return next(
        (o for o in _ALLOWED_ORIGINS if o.startswith("https://")),
        "https://treesight.hrdcrprwn.com",
    )


# ---------------------------------------------------------------------------
# POST /api/billing/checkout  — create a Stripe Checkout session
# ---------------------------------------------------------------------------
@bp.route(
    route="billing/checkout",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def billing_checkout(
    req: func.HttpRequest,
    *,
    auth_claims: dict,
    user_id: str,
) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)

    if not _stripe_configured():
        return error_response(503, "Billing not configured", req=req)

    stripe = _get_stripe()
    origin = _safe_origin(req)

    from treesight.constants import DEFAULT_CURRENCY, SUPPORTED_CURRENCIES

    # Determine currency (default GBP, allow override via ?currency= or JSON body)
    currency = req.params.get("currency", "").upper()
    if not currency and req.get_body():
        try:
            body = json.loads(req.get_body())
            currency = body.get("currency", "").upper()
        except (ValueError, UnicodeDecodeError):
            pass
    if currency not in SUPPORTED_CURRENCIES:
        currency = DEFAULT_CURRENCY
    if currency == "USD":
        price_id = STRIPE_PRICE_ID_PRO_USD
    elif currency == "EUR":
        price_id = STRIPE_PRICE_ID_PRO_EUR
    else:
        price_id = STRIPE_PRICE_ID_PRO_GBP

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{origin}?billing=success",
            cancel_url=f"{origin}?billing=cancel",
            client_reference_id=user_id,
            metadata={"user_id": user_id, "currency": currency},
            # UK compliance: collect billing address for VAT
            billing_address_collection="required",
            # Let Stripe Tax handle VAT automatically
            automatic_tax={"enabled": True},
            # UK Consumer Contracts Regulations — cancellation right
            consent_collection={"terms_of_service": "required"},
            custom_text={
                "terms_of_service_acceptance": {
                    "message": (
                        "I agree to the [Terms of Service]"
                        "(https://treesight.hrdcrprwn.com/terms.html)"
                        " and acknowledge my right to cancel within"
                        " 14 days under the Consumer Contracts"
                        " Regulations 2013."
                    )
                }
            },
            # Allow promotion codes
            allow_promotion_codes=True,
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe checkout session creation failed")
        msg = getattr(exc, "user_message", None) or "unknown"
        return error_response(502, f"Payment provider error: {msg}", req=req)

    return func.HttpResponse(
        json.dumps({"checkout_url": session.url}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# POST /api/billing/portal  — create a Stripe Customer Portal session
# ---------------------------------------------------------------------------
@bp.route(route="billing/portal", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def billing_portal(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)

    if not _stripe_configured():
        return error_response(503, "Billing not configured", req=req)

    from treesight.security.billing import get_subscription

    sub = get_subscription(user_id)
    customer_id = sub.get("stripe_customer_id")
    if not customer_id:
        return error_response(404, "No active subscription found", req=req)

    stripe = _get_stripe()
    origin = _safe_origin(req)

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{origin}?billing=portal-return",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe portal session creation failed")
        msg = getattr(exc, "user_message", None) or "unknown"
        return error_response(502, f"Payment provider error: {msg}", req=req)

    return func.HttpResponse(
        json.dumps({"portal_url": session.url}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# POST /api/billing/webhook  — Stripe webhook receiver
# ---------------------------------------------------------------------------
@bp.route(route="billing/webhook", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def billing_webhook(req: func.HttpRequest) -> func.HttpResponse:
    if not _stripe_configured():
        return func.HttpResponse("Billing not configured", status_code=503)

    stripe = _get_stripe()

    payload = req.get_body()
    sig_header = req.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.SignatureVerificationError:
        logger.warning("Stripe webhook signature verification failed")
        return func.HttpResponse("Invalid signature", status_code=400)
    except ValueError:
        logger.warning("Stripe webhook payload invalid")
        return func.HttpResponse("Invalid payload", status_code=400)

    _handle_event(event)

    return func.HttpResponse("ok", status_code=200)


def _handle_event(event: dict) -> None:
    """Dispatch Stripe webhook events to subscription record updates."""
    from treesight.security.billing import save_subscription

    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    # Map Stripe customer to our user_id via client_reference_id or metadata
    user_id = (
        obj.get("client_reference_id")
        or obj.get("metadata", {}).get("user_id")
        or _user_id_from_customer(obj.get("customer"))
    )

    if not user_id:
        logger.warning("Stripe event %s has no user_id mapping — skipping", event_type)
        return

    if event_type == "checkout.session.completed":
        save_subscription(
            user_id,
            {
                "tier": "pro",
                "status": "active",
                "stripe_customer_id": obj.get("customer"),
                "stripe_subscription_id": obj.get("subscription"),
            },
        )
        logger.info("Pro subscription activated for user=%s", user_id)

    elif event_type in (
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        status = obj.get("status", "unknown")
        tier = "pro" if status == "active" else "free"
        save_subscription(
            user_id,
            {
                "tier": tier,
                "status": status,
                "stripe_customer_id": obj.get("customer"),
                "stripe_subscription_id": obj.get("id"),
            },
        )
        logger.info("Subscription %s for user=%s status=%s", event_type, user_id, status)

    elif event_type == "invoice.payment_failed":
        save_subscription(
            user_id,
            {
                "tier": "free",
                "status": "past_due",
                "stripe_customer_id": obj.get("customer"),
                "stripe_subscription_id": obj.get("subscription"),
            },
        )
        logger.warning("Payment failed for user=%s", user_id)


def _user_id_from_customer(customer_id: str | None) -> str | None:
    """Reverse-lookup user_id from Stripe customer ID.

    This scans subscription blobs — acceptable at webhook scale.
    For high volume, add a customer→user index blob.
    """
    if not customer_id:
        return None

    from treesight.constants import PIPELINE_PAYLOADS_CONTAINER
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        from treesight.constants import SUBSCRIPTIONS_PREFIX

        prefix = f"{SUBSCRIPTIONS_PREFIX}/"
        blobs = storage.list_blobs(PIPELINE_PAYLOADS_CONTAINER, prefix=prefix)
        for blob_name in blobs:
            try:
                record = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, blob_name)
                if record.get("stripe_customer_id") == customer_id:
                    return blob_name.removeprefix(prefix).removesuffix(".json")
            except Exception:
                logger.debug("Skipping unreadable blob %s", blob_name)
                continue
    except Exception:
        logger.warning("Could not scan subscriptions for customer=%s", customer_id)
    return None


# ---------------------------------------------------------------------------
# GET /api/billing/status  — current user's subscription status
# ---------------------------------------------------------------------------
@bp.route(route="billing/status", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def billing_status(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)

    from treesight.security.billing import get_subscription
    from treesight.security.quota import check_quota

    sub = get_subscription(user_id)
    remaining = check_quota(user_id)

    return func.HttpResponse(
        json.dumps(
            {
                "tier": sub.get("tier", "free"),
                "status": sub.get("status", "none"),
                "runs_remaining": remaining,
                "billing_configured": _stripe_configured(),
            }
        ),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )

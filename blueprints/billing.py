"""Billing blueprint — Stripe Checkout, webhooks, and subscription status.

UK compliance: Stripe Tax handles VAT, customer portal handles self-service
cancellation (Consumer Contracts Regulations 2013 — 14-day cooling-off).
"""

import json
import logging
from urllib.parse import urlparse

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


def _cosmos_available() -> bool:
    """Return True if Cosmos DB is configured."""
    from treesight import config

    return bool(config.COSMOS_ENDPOINT)


_LOCAL_EMULATION_ORIGINS = {
    "http://localhost:4280",
    "http://127.0.0.1:4280",
    "http://localhost:1111",
    "http://127.0.0.1:1111",
}


def _stripe_configured() -> bool:
    return bool(
        STRIPE_API_KEY
        and STRIPE_WEBHOOK_SECRET
        and (STRIPE_PRICE_ID_PRO_EUR or STRIPE_PRICE_ID_PRO_GBP or STRIPE_PRICE_ID_PRO_USD)
    )


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


def _tier_emulation_allowed(req: func.HttpRequest) -> bool:
    """Allow plan emulation only from local development origins."""
    origin = req.headers.get("Origin", "")
    if origin in _LOCAL_EMULATION_ORIGINS:
        return True
    try:
        hostname = urlparse(req.url).hostname or ""
    except Exception:
        return False
    return hostname in {"localhost", "127.0.0.1"}


def _billing_status_payload(user_id: str, req: func.HttpRequest) -> dict:
    from treesight.security.billing import (
        get_effective_subscription,
        get_subscription,
        get_subscription_emulation,
        plan_capabilities,
        supported_tiers,
    )
    from treesight.security.feature_gate import GATED_PRICE_LABELS, billing_allowed
    from treesight.security.quota import check_quota

    subscription = get_subscription(user_id)
    effective = get_effective_subscription(user_id)
    emulation = get_subscription_emulation(user_id)
    capabilities = plan_capabilities(effective.get("tier"))

    gated = not billing_allowed(user_id)

    payload = {
        "tier": effective.get("tier", "free"),
        "status": effective.get("status", "none"),
        "runs_remaining": check_quota(user_id),
        "billing_configured": _stripe_configured(),
        "billing_gated": gated,
        "tier_source": "emulated" if effective.get("emulated") else "billing",
        "capabilities": capabilities,
        "subscription": {
            "tier": subscription.get("tier", "free"),
            "status": subscription.get("status", "none"),
        },
        "emulation": {
            "available": _tier_emulation_allowed(req),
            "active": bool(emulation),
            "tier": emulation.get("tier") if emulation else None,
            "tiers": list(supported_tiers()),
        },
    }

    if gated:
        payload["price_labels"] = GATED_PRICE_LABELS

    return payload


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

    if user_id == "anonymous":
        return error_response(401, "Authentication required for billing", req=req)

    from treesight.security.feature_gate import billing_allowed

    if not billing_allowed(user_id):
        return error_response(
            403,
            "Billing is not yet available for your account. "
            "Use the contact form to express interest and we'll be in touch.",
            req=req,
        )

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
            pass  # Malformed body — fall through to default currency
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

    if user_id == "anonymous":
        return error_response(401, "Authentication required for billing", req=req)

    from treesight.security.feature_gate import billing_allowed

    if not billing_allowed(user_id):
        return error_response(403, "Billing is not available for your account", req=req)

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

    Queries the Cosmos subscriptions container (indexed on stripe_customer_id)
    when available; falls back to scanning subscription blobs.
    """
    if not customer_id:
        return None

    if _cosmos_available():
        try:
            from treesight.storage import cosmos

            results = cosmos.query_items(
                "subscriptions",
                "SELECT c.user_id FROM c WHERE c.stripe_customer_id = @cid",
                parameters=[{"name": "@cid", "value": customer_id}],
            )
            if results:
                return results[0].get("user_id")
        except Exception:
            logger.warning(
                "Cosmos reverse lookup failed for customer=%s, falling back to blob",
                customer_id,
                exc_info=True,
            )

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

    return func.HttpResponse(
        json.dumps(_billing_status_payload(user_id, req)),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="billing/emulation", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS
)
@require_auth
def billing_emulation(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)

    if not _tier_emulation_allowed(req):
        if user_id == "anonymous":
            return error_response(401, "Authentication required for billing", req=req)
        return error_response(
            403, "Tier emulation is only available from local development origins", req=req
        )

    try:
        body = json.loads(req.get_body() or b"{}")
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    requested_tier = str(body.get("tier", "")).strip().lower()

    from treesight.security.billing import clear_subscription_emulation, save_subscription_emulation

    try:
        if requested_tier in {"", "actual", "clear", "none"}:
            clear_subscription_emulation(user_id)
        else:
            save_subscription_emulation(user_id, requested_tier)
    except ValueError as exc:
        return error_response(400, str(exc), req=req)

    return func.HttpResponse(
        json.dumps(_billing_status_payload(user_id, req)),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# POST /api/billing/interest  — express interest in billing / upgrading
# ---------------------------------------------------------------------------
@bp.route(
    route="billing/interest",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def billing_interest(
    req: func.HttpRequest,
    *,
    auth_claims: dict,
    user_id: str,
) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return cors_preflight(req)

    import uuid
    from datetime import UTC, datetime

    from blueprints._helpers import EMAIL_RE, sanitise
    from treesight.constants import PIPELINE_PAYLOADS_CONTAINER
    from treesight.email import send_contact_notification
    from treesight.security.rate_limit import form_limiter, get_client_ip
    from treesight.storage.client import BlobStorageClient

    if not form_limiter.is_allowed(get_client_ip(req)):
        return error_response(429, "Rate limit exceeded — try again later", req=req)

    try:
        body = req.get_json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}

    email = sanitise(body.get("email", ""))
    if not email or not EMAIL_RE.match(email):
        return error_response(400, "Valid email is required", req=req)

    organization = sanitise(body.get("organization", ""))
    message = sanitise(body.get("message", ""))

    submission_id = str(uuid.uuid4())
    record = {
        "submission_id": submission_id,
        "source": "billing_interest",
        "user_id": user_id,
        "email": email,
        "organization": organization,
        "message": message,
        "submitted_at": datetime.now(UTC).isoformat(),
    }

    storage = BlobStorageClient()
    storage.upload_json(
        PIPELINE_PAYLOADS_CONTAINER,
        f"contact-submissions/{submission_id}.json",
        record,
    )

    send_contact_notification(record)

    return func.HttpResponse(
        json.dumps({"status": "received", "submission_id": submission_id}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )

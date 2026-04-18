"""EUDR compliance endpoints — coordinate conversion, assessment (M4 §4.9–4.10).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import contextlib
import json
import logging
import math
import os
import re

import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response
from treesight.security.rate_limit import get_client_ip, pipeline_limiter

bp = func.Blueprint()

# Limits
_MAX_PLOTS = 200
_MAX_BODY_BYTES = 65_536  # 64 KiB
_NAME_RE = re.compile(r"[^A-Za-z0-9\s\-_.]+")
_MAX_NAME_LEN = 100


def _sanitise_name(val: str) -> str:
    if not isinstance(val, str):
        return ""
    return _NAME_RE.sub("", val).strip()[:_MAX_NAME_LEN]


def _validate_plot(i: int, p: dict) -> dict | str:
    """Validate a single plot entry. Returns dict on success or error string."""
    if not isinstance(p, dict):
        return f"Plot {i} must be an object"

    name = _sanitise_name(p.get("name", f"Plot {i + 1}"))
    entry: dict = {"name": name}

    if "coordinates" in p:
        coords = p["coordinates"]
        if not isinstance(coords, list) or len(coords) < 3:
            return f"Plot {i} coordinates must have >= 3 points"
        for j, c in enumerate(coords):
            if not isinstance(c, list) or len(c) < 2:
                return f"Plot {i} coordinate {j} must be [lon, lat]"
            try:
                clon = float(c[0])
                clat = float(c[1])
            except (TypeError, ValueError):
                return f"Plot {i} coordinate {j} lon/lat must be numbers"
            if not (-180 <= clon <= 180 and -90 <= clat <= 90):
                return f"Plot {i} coordinate {j} out of range"
        entry["coordinates"] = [[float(c[0]), float(c[1])] for c in coords]
    elif "lon" in p and "lat" in p:
        try:
            lon = float(p["lon"])
            lat = float(p["lat"])
        except (TypeError, ValueError):
            return f"Plot {i} lon/lat must be numbers"
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return f"Plot {i} coordinates out of range"
        entry["lon"] = lon
        entry["lat"] = lat
        if "radius_m" in p:
            with contextlib.suppress(TypeError, ValueError):
                entry["radius_m"] = float(p["radius_m"])
    else:
        return f"Plot {i} needs 'lon'+'lat' or 'coordinates'"

    return entry


def _validate_convert_request(
    req: func.HttpRequest,
) -> tuple[list[dict], str, float] | func.HttpResponse:
    """Validate convert-coordinates request.

    Returns (validated_plots, doc_name, buffer_m) or error response.
    """
    if not pipeline_limiter.is_allowed(get_client_ip(req)):
        return error_response(429, "Too many requests — please wait before trying again", req=req)

    try:
        check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    raw = req.get_body()
    if len(raw) > _MAX_BODY_BYTES:
        return error_response(400, f"Body too large (max {_MAX_BODY_BYTES} bytes)", req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    if not isinstance(body, dict):
        return error_response(400, "Expected JSON object", req=req)

    plots = body.get("plots", [])
    if not isinstance(plots, list) or not plots:
        return error_response(400, "'plots' must be a non-empty array", req=req)
    if len(plots) > _MAX_PLOTS:
        return error_response(400, f"Maximum {_MAX_PLOTS} plots per request", req=req)

    validated = []
    for i, p in enumerate(plots):
        result = _validate_plot(i, p)
        if isinstance(result, str):
            return error_response(400, result, req=req)
        validated.append(result)

    doc_name = _sanitise_name(body.get("doc_name", "EUDR Plots")) or "EUDR Plots"
    try:
        buffer_m = float(body.get("buffer_m", 100.0))
    except (TypeError, ValueError):
        return error_response(400, "'buffer_m' must be a number", req=req)
    if buffer_m <= 0 or not math.isfinite(buffer_m):
        return error_response(400, "'buffer_m' must be a positive finite number", req=req)

    return validated, doc_name, buffer_m


@bp.route(
    route="convert-coordinates",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def convert_coordinates(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/convert-coordinates — convert coordinate plots to KML.

    Accepts a JSON body with an array of plots (points or polygons) and
    returns a downloadable KML document.

    Request body::

        {
            "doc_name": "My EUDR Plots",
            "buffer_m": 100,
            "plots": [
                {"name": "Plot A", "lon": 2.35, "lat": 48.86},
                {"name": "Plot B", "lon": 2.36, "lat": 48.87, "radius_m": 200},
                {"name": "Block C", "coordinates": [[lon,lat], [lon,lat], ...]}
            ]
        }

    Response: KML file as ``application/vnd.google-earth.kml+xml``.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    result = _validate_convert_request(req)
    if isinstance(result, func.HttpResponse):
        return result
    validated, doc_name, buffer_m = result

    from treesight.pipeline.eudr import coords_to_kml

    kml_str = coords_to_kml(validated, doc_name=doc_name, buffer_m=buffer_m)

    headers = cors_headers(req)
    headers["Content-Disposition"] = f'attachment; filename="{doc_name}.kml"'

    return func.HttpResponse(
        kml_str,
        status_code=200,
        mimetype="application/vnd.google-earth.kml+xml",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# EUDR billing endpoints (#613)
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


@bp.route(
    route="eudr/billing",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def eudr_billing_status(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/eudr/billing — EUDR billing status for the caller's org."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    from treesight.security.eudr_billing import get_eudr_billing_status
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return func.HttpResponse(
            json.dumps(get_eudr_billing_status("")),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers(req),
        )

    status = get_eudr_billing_status(org["org_id"])
    return func.HttpResponse(
        json.dumps(status),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="eudr/entitlement",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def eudr_entitlement_check(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/eudr/entitlement — check if the org can submit an assessment."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    from treesight.security.eudr_billing import check_eudr_entitlement
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return func.HttpResponse(
            json.dumps({"allowed": False, "reason": "no_org"}),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers(req),
        )

    result = check_eudr_entitlement(org["org_id"])
    return func.HttpResponse(
        json.dumps(result),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="eudr/subscribe",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def eudr_subscribe(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/eudr/subscribe — create Stripe Checkout for EUDR plan.

    Owner-only. Creates a checkout session with both the base subscription
    price and the metered usage price.
    """
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    from treesight.security.eudr_billing import is_org_owner
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return error_response(404, "You do not belong to an organisation", req=req)

    org_id = org["org_id"]
    if not is_org_owner(org_id, user_id):
        return error_response(403, "Only organisation owners can subscribe", req=req)

    # Check not already subscribed
    billing = org.get("billing", {})
    if billing.get("eudr_status") == "active":
        return error_response(409, "Organisation already has an active EUDR subscription", req=req)

    from treesight.config import (
        STRIPE_API_KEY,
        STRIPE_PRICE_ID_EUDR_BASE_EUR,
        STRIPE_PRICE_ID_EUDR_BASE_GBP,
        STRIPE_PRICE_ID_EUDR_BASE_USD,
        STRIPE_PRICE_ID_EUDR_METERED_EUR,
        STRIPE_PRICE_ID_EUDR_METERED_GBP,
        STRIPE_PRICE_ID_EUDR_METERED_USD,
        STRIPE_WEBHOOK_SECRET,
    )

    if not STRIPE_API_KEY or not STRIPE_WEBHOOK_SECRET:
        return error_response(503, "Billing not configured", req=req)

    from treesight.constants import DEFAULT_CURRENCY, SUPPORTED_CURRENCIES

    # Determine currency
    currency = req.params.get("currency", "").upper()
    if not currency and req.get_body():
        with contextlib.suppress(ValueError, UnicodeDecodeError):
            body = json.loads(req.get_body())
            currency = body.get("currency", "").upper() if isinstance(body, dict) else ""
    if currency not in SUPPORTED_CURRENCIES:
        currency = DEFAULT_CURRENCY

    # Select price IDs for this currency
    base_prices = {
        "GBP": STRIPE_PRICE_ID_EUDR_BASE_GBP,
        "USD": STRIPE_PRICE_ID_EUDR_BASE_USD,
        "EUR": STRIPE_PRICE_ID_EUDR_BASE_EUR,
    }
    metered_prices = {
        "GBP": STRIPE_PRICE_ID_EUDR_METERED_GBP,
        "USD": STRIPE_PRICE_ID_EUDR_METERED_USD,
        "EUR": STRIPE_PRICE_ID_EUDR_METERED_EUR,
    }

    base_price = base_prices.get(currency)
    metered_price = metered_prices.get(currency)
    if not base_price or not metered_price:
        return error_response(503, f"EUDR pricing not configured for {currency}", req=req)

    import stripe

    stripe.api_key = STRIPE_API_KEY

    from blueprints._helpers import _cors_origin

    origin = _cors_origin(req) or os.environ.get("PRIMARY_SITE_URL", "")
    if not origin:
        return error_response(503, "Site URL not configured", req=req)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[
                {"price": base_price, "quantity": 1},
                {"price": metered_price},
            ],
            success_url=f"{origin}/eudr/?subscribed=true",
            cancel_url=f"{origin}/eudr/?billing=cancel",
            client_reference_id=user_id,
            metadata={
                "user_id": user_id,
                "org_id": org_id,
                "product": "eudr",
                "currency": currency,
            },
            subscription_data={
                "metadata": {
                    "user_id": user_id,
                    "org_id": org_id,
                    "product": "eudr",
                    "currency": currency,
                }
            },
            billing_address_collection="required",
            automatic_tax={"enabled": True},
            consent_collection={"terms_of_service": "required"},
            custom_text={
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
            allow_promotion_codes=True,
        )
    except stripe.StripeError as exc:
        logger.exception("EUDR Stripe checkout session creation failed")
        msg = getattr(exc, "user_message", None) or "unknown"
        return error_response(502, f"Payment provider error: {msg}", req=req)

    return func.HttpResponse(
        json.dumps({"checkout_url": session.url}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )

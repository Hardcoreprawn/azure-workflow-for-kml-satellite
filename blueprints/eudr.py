"""EUDR compliance endpoints — HTTP dispatch shell (M4 §4.9–4.10).

Pure business logic lives in treesight/eudr/.
NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import contextlib
import json
import logging
import math
import os
from typing import Any

import azure.durable_functions as df
import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response, require_auth
from treesight.pipeline.enrichment.determination import as_screening_determination
from treesight.eudr.plots import sanitise_name, validate_plot
from treesight.security.rate_limit import get_client_ip, get_pipeline_limiter

bp = func.Blueprint()
# Limits
_MAX_PLOTS = 200
_MAX_BODY_BYTES = 65_536  # 64 KiB

logger = logging.getLogger(__name__)


def _fetch_org_run_records(user_id: str, limit: int = 250) -> list[dict]:
    """Fetch and merge run records for all members of the user's org."""
    from blueprints.pipeline.history import _fetch_submission_records  # type: ignore[reportPrivateUsage]
    from treesight.eudr.usage import org_member_ids_for_user

    all_records: list[dict] = []
    for member_id in org_member_ids_for_user(user_id):
        all_records.extend(_fetch_submission_records(member_id, limit, offset=0))
    all_records.sort(key=lambda r: str(r.get("submitted_at", "")), reverse=True)
    return all_records[:limit]


def _resolve_manifest_path(output: object) -> str | None:
    """Extract the enrichment manifest blob path from a DF status output."""
    from blueprints.pipeline._status import _reshape_output  # type: ignore[reportPrivateUsage]

    if isinstance(output, dict):
        output = _reshape_output(output)
    if isinstance(output, dict):
        return output.get("enrichment_manifest") or output.get("enrichmentManifest") or None
    return None


def _validate_convert_request(
    req: func.HttpRequest,
) -> tuple[list[dict], str, float] | func.HttpResponse:
    """Validate and return (plots, doc_name, buffer_m) or an error HttpResponse."""
    if not get_pipeline_limiter().is_allowed(get_client_ip(req)):
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
        result = validate_plot(i, p)
        if isinstance(result, str):
            return error_response(400, result, req=req)
        validated.append(result)

    doc_name = sanitise_name(body.get("doc_name", "EUDR Plots")) or "EUDR Plots"
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
    """POST /api/convert-coordinates — convert coordinate plots to KML."""
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


@bp.route(
    route="eudr/usage",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def eudr_usage_status(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """GET /api/eudr/usage — org-scoped usage and billing summary for dashboard."""
    from treesight.eudr.usage import eudr_usage_payload
    from treesight.security.eudr_billing import get_eudr_billing_status
    from treesight.security.orgs import get_user_org

    records = _fetch_org_run_records(user_id, limit=400)
    org = get_user_org(user_id)
    org_id = org.get("org_id", "") if isinstance(org, dict) else ""
    billing = get_eudr_billing_status(org_id, user_id=user_id)
    payload = eudr_usage_payload(user_id, records, org=org, billing=billing)
    return func.HttpResponse(
        json.dumps(payload),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="eudr/billing",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def eudr_billing_status(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """GET /api/eudr/billing — EUDR billing status for the caller's org."""
    from treesight.security.eudr_billing import get_eudr_billing_status
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return func.HttpResponse(
            json.dumps(get_eudr_billing_status("", user_id=user_id)),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers(req),
        )

    status = get_eudr_billing_status(org["org_id"], user_id=user_id)
    return func.HttpResponse(
        json.dumps(status),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


@bp.route(
    route="eudr/subscribe",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
<<<<<<< HEAD
@require_auth
def eudr_subscribe(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """POST /api/eudr/subscribe — create Stripe Checkout for EUDR plan.

    Owner-only. Creates a checkout session with both the base subscription
    price and the metered usage price.
    """
=======
def eudr_subscribe(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/eudr/subscribe — owner-only Stripe Checkout for EUDR plan."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

>>>>>>> 0b99e2f (refactor: address code review — fix arch boundary violations and lat/lon handling)
    from treesight.security.eudr_billing import is_org_owner
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return error_response(404, "You do not belong to an organisation", req=req)

    org_id = org["org_id"]
    if not is_org_owner(org_id, user_id):
        return error_response(403, "Only organisation owners can subscribe", req=req)

    billing = org.get("billing", {})
    if billing.get("eudr_status") == "active":
        return error_response(409, "Organisation already has an active EUDR subscription", req=req)

    from treesight.config import STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET
    from treesight.constants import DEFAULT_CURRENCY, SUPPORTED_CURRENCIES
    from treesight.eudr.stripe_checkout import resolve_eudr_prices

    if not STRIPE_API_KEY or not STRIPE_WEBHOOK_SECRET:
        return error_response(503, "Billing not configured", req=req)

    currency = req.params.get("currency", "").upper()
    if not currency and req.get_body():
        with contextlib.suppress(ValueError, UnicodeDecodeError):
            body = json.loads(req.get_body())
            currency = body.get("currency", "").upper() if isinstance(body, dict) else ""
    if currency not in SUPPORTED_CURRENCIES:
        currency = DEFAULT_CURRENCY

    base_price, metered_price = resolve_eudr_prices(currency)
    if not base_price or not metered_price:
        return error_response(503, f"EUDR pricing not configured for {currency}", req=req)

    import stripe

    stripe.api_key = STRIPE_API_KEY

    from blueprints._helpers import _cors_origin

    origin = _cors_origin(req) or os.environ.get("PRIMARY_SITE_URL", "")
    if not origin:
        return error_response(503, "Site URL not configured", req=req)

    from treesight.eudr.stripe_checkout import build_eudr_checkout_kwargs

    checkout_kwargs = build_eudr_checkout_kwargs(
        user_id=user_id,
        org_id=org_id,
        base_price=base_price,
        metered_price=metered_price,
        origin=origin,
        currency=currency,
    )

    try:
        session = stripe.checkout.Session.create(**checkout_kwargs)
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


@bp.route(
    route="eudr/summary-export",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@bp.durable_client_input(client_name="client")
async def eudr_summary_export(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """GET /api/eudr/summary-export — aggregated per-parcel CSV across org runs (#674)."""
    return await _eudr_summary_export(req, client)


async def _eudr_summary_export(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    """Inner implementation for testing without Azure middleware."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    from treesight.constants import DEFAULT_OUTPUT_CONTAINER
    from treesight.eudr.export import build_summary_csv, summary_rows_from_manifest
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    run_records = _fetch_org_run_records(user_id, limit=20)

    all_rows: list[dict[str, Any]] = []
    for record in run_records:
        instance_id = record.get("instance_id") or record.get("run_id", "")
        submitted_at = record.get("submitted_at", "")
        if not instance_id:
            continue

        try:
            status = await client.get_status(instance_id, show_input=False)
            if not status or not status.output:
                continue
            output = status.output
            if isinstance(output, str):
                with contextlib.suppress(Exception):
                    output = json.loads(output)
            manifest_path = _resolve_manifest_path(output)
            if not manifest_path:
                continue

            manifest = storage.download_json(DEFAULT_OUTPUT_CONTAINER, manifest_path)
            rows = summary_rows_from_manifest(instance_id, submitted_at, manifest, record)
            all_rows.extend(rows)
        except Exception:
            logger.warning("summary-export: skipping run %s due to fetch error", instance_id)
            continue

    if not all_rows:
        return error_response(404, "No completed EUDR runs found for export", req=req)

    csv_body = build_summary_csv(all_rows)
    headers = cors_headers(req)
    headers["Content-Disposition"] = 'attachment; filename="eudr_summary_export.csv"'
    return func.HttpResponse(
        csv_body,
        status_code=200,
        mimetype="text/csv",
        headers=headers,
    )

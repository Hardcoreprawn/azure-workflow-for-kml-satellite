"""EUDR compliance endpoints — coordinate conversion, assessment (M4 §4.9–4.10).

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
See blueprints/pipeline.py module docstring for details.
"""

import contextlib
import csv
import io
import json
import logging
import math
import os
import re
from datetime import UTC, datetime
from typing import Any

import azure.durable_functions as df
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


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    with contextlib.suppress(ValueError, TypeError):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _month_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _last_n_month_keys(n: int, *, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    y = now.year
    m = now.month
    keys: list[str] = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    keys.reverse()
    return keys


def _org_member_ids_for_user(user_id: str) -> list[str]:
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return [user_id]
    members = org.get("members", [])
    member_ids: list[str] = []
    for member in members:
        if isinstance(member, dict):
            mid = str(member.get("user_id", "")).strip()
            if mid and mid not in member_ids:
                member_ids.append(mid)
    if user_id not in member_ids:
        member_ids.append(user_id)
    return member_ids


def _fetch_org_run_records(user_id: str, limit: int = 250) -> list[dict]:
    from blueprints.pipeline.history import _fetch_submission_records

    all_records: list[dict] = []
    for member_id in _org_member_ids_for_user(user_id):
        all_records.extend(_fetch_submission_records(member_id, limit, offset=0, max_results=300))
    all_records.sort(key=lambda record: str(record.get("submitted_at", "")), reverse=True)
    return all_records[:limit]


def _eudr_usage_payload(user_id: str) -> dict:
    from treesight.constants import EUDR_INCLUDED_PARCELS
    from treesight.security.eudr_billing import get_eudr_billing_status
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    org_id = org.get("org_id") if isinstance(org, dict) else ""
    billing = get_eudr_billing_status(org_id or "")

    period_used = int(billing.get("period_parcels_used", 0) or 0)
    included = int(billing.get("included_parcels", EUDR_INCLUDED_PARCELS) or EUDR_INCLUDED_PARCELS)
    overage = max(period_used - included, 0)

    # Tier break guidance for graduated EUDR rates.
    next_threshold = None
    next_rate = None
    for threshold, rate in ((100, 2.50), (500, 1.80)):
        if period_used < threshold:
            next_threshold = threshold
            next_rate = rate
            break

    records = _fetch_org_run_records(user_id, limit=400)
    month_keys = _last_n_month_keys(6)
    by_month: dict[str, dict[str, int]] = {
        k: {"parcels": 0, "runs": 0, "overage_runs": 0} for k in month_keys
    }
    for record in records:
        submitted = _parse_iso_datetime(str(record.get("submitted_at", "")))
        if not submitted:
            continue
        key = _month_key(submitted)
        if key not in by_month:
            continue
        by_month[key]["runs"] += 1
        by_month[key]["parcels"] += int(record.get("aoi_count", 0) or 0)
        if str(record.get("billing_type", "")) == "overage":
            by_month[key]["overage_runs"] += 1

    months = [
        {
            "month": key,
            "runs": by_month[key]["runs"],
            "parcels": by_month[key]["parcels"],
            "overageRuns": by_month[key]["overage_runs"],
        }
        for key in month_keys
    ]

    estimated_spend_gbp = round((overage * 3.0), 2)

    return {
        "current": {
            "periodParcelsUsed": period_used,
            "includedParcels": included,
            "overageParcels": overage,
            "estimatedSpendGbp": estimated_spend_gbp,
            "nextTierThreshold": next_threshold,
            "nextTierRateGbp": next_rate,
            "parcelsToNextTier": (next_threshold - period_used) if next_threshold else 0,
            "within20PercentOfNextTier": bool(
                next_threshold and period_used >= int(next_threshold * 0.8)
            ),
        },
        "history": months,
    }


@bp.route(
    route="eudr/usage",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def eudr_usage_status(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/eudr/usage — org-scoped usage and billing summary for dashboard."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    payload = _eudr_usage_payload(user_id)
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


# ---------------------------------------------------------------------------
# §5 — GET /api/eudr/summary-export  (#674)
# ---------------------------------------------------------------------------

_SUMMARY_CSV_FIELDS = [
    "run_id",
    "submitted_at",
    "parcel_name",
    "area_ha",
    "center_lat",
    "center_lon",
    "determination_status",
    "determination_confidence",
    "determination_flags",
    "overridden",
    "override_reason",
    "note",
]


def _summary_rows_from_manifest(
    run_id: str,
    submitted_at: str,
    manifest: dict[str, Any],
    run_record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Extract per-AOI CSV rows from a single run manifest + run record annotations."""
    per_aoi = manifest.get("per_aoi_enrichment", [])
    if not per_aoi:
        return []

    parcel_notes: dict[str, str] = {}
    parcel_overrides: dict[str, dict[str, Any]] = {}
    if run_record:
        parcel_notes = run_record.get("parcel_notes") or {}
        parcel_overrides = run_record.get("parcel_overrides") or {}

    rows = []
    for idx, aoi in enumerate(per_aoi):
        parcel_key = str(idx)
        center = aoi.get("center", {})
        det = aoi.get("determination", {})
        override = parcel_overrides.get(parcel_key, {})
        overridden = bool(override) and not override.get("reverted")

        rows.append(
            {
                "run_id": run_id,
                "submitted_at": submitted_at,
                "parcel_name": aoi.get("name", parcel_key),
                "area_ha": aoi.get("area_ha", ""),
                "center_lat": center.get("lat", ""),
                "center_lon": center.get("lon", ""),
                "determination_status": (
                    "error"
                    if "error" in aoi
                    else ("compliant" if det.get("deforestation_free") else "non_compliant")
                ),
                "determination_confidence": det.get("confidence", ""),
                "determination_flags": "; ".join(det.get("flags", [])),
                "overridden": "yes" if overridden else "no",
                "override_reason": override.get("reason", "") if overridden else "",
                "note": parcel_notes.get(parcel_key, ""),
            }
        )
    return rows


def _build_summary_csv(rows: list[dict[str, Any]]) -> str:
    """Serialise a list of summary row dicts as a CSV string."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_SUMMARY_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


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

    from blueprints.pipeline._helpers import _reshape_output
    from treesight.constants import DEFAULT_OUTPUT_CONTAINER
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
            if isinstance(output, dict):
                output = _reshape_output(output)
            manifest_path = (
                output.get("enrichment_manifest") or output.get("enrichmentManifest")
                if isinstance(output, dict)
                else None
            )
            if not manifest_path:
                continue

            manifest = storage.download_json(DEFAULT_OUTPUT_CONTAINER, manifest_path)
            rows = _summary_rows_from_manifest(instance_id, submitted_at, manifest, record)
            all_rows.extend(rows)
        except Exception:
            logger.warning("summary-export: skipping run %s due to fetch error", instance_id)
            continue

    if not all_rows:
        return error_response(404, "No completed EUDR runs found for export", req=req)

    csv_body = _build_summary_csv(all_rows)
    headers = cors_headers(req)
    headers["Content-Disposition"] = 'attachment; filename="eudr_summary_export.csv"'
    return func.HttpResponse(
        csv_body,
        status_code=200,
        mimetype="text/csv",
        headers=headers,
    )

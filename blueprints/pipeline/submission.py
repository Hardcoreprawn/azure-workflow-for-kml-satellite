"""Submission HTTP endpoints for signed-in analysis requests.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
See blueprints/pipeline/__init__.py for details.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import azure.functions as func

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response
from treesight.billing.accounting import (
    MemberCapExceededError,
    OrgNotFoundError,
    QuotaExhaustedError,
    finalize_run,
    reserve_run,
)
from treesight.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_PROVIDER, MAX_KML_FILE_SIZE_BYTES
from treesight.pipeline.concurrency import at_concurrency_cap
from treesight.security.billing import get_effective_subscription, plan_capabilities
from treesight.security.orgs import get_user_org
from treesight.security.redact import redact_user_id as _redact

from . import bp
from .history import _extract_submission_context, _persist_submission_record

logger = logging.getLogger(__name__)


def _finalize_run_on_failure(org_id: str, instance_id: str) -> None:
    """Best-effort run refund on submission failure — never raises."""
    try:
        finalize_run(org_id=org_id, instance_id=instance_id, status="failed")
    except Exception:
        logger.exception("Failed to finalize run for org=%s instance=%s", org_id, instance_id)


_PRIOR_SUBMISSION_ID_RE = __import__("re").compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    __import__("re").IGNORECASE,
)


def _quota_already_consumed(user_id: str, prior_submission_id: str) -> bool:
    """Return True when upload-token already consumed quota for *prior_submission_id*.

    Reads the ticket blob written by the upload-token endpoint and checks that
    it belongs to *user_id*.  Any lookup failure is treated as "not consumed"
    so the fallback path still charges quota rather than leaking a free slot.
    """
    if not _PRIOR_SUBMISSION_ID_RE.match(prior_submission_id):
        return False
    try:
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient()
        ticket = storage.download_json(
            DEFAULT_INPUT_CONTAINER, f".tickets/{prior_submission_id}.json"
        )
        return isinstance(ticket, dict) and ticket.get("user_id") == user_id
    except Exception:
        logger.debug("Prior quota ticket not found for prior_submission_id=%s", prior_submission_id)
        return False


def _submission_plan_overrides(user_id: str) -> dict[str, Any]:
    """Return orchestration input overrides for the signed-in user's tier."""
    try:
        subscription = get_effective_subscription(user_id)
        plan = plan_capabilities(subscription.get("tier"))
    except Exception:
        logger.exception(
            "Billing lookup unavailable for user=%s — defaulting to free-tier controls",
            user_id,
        )
        plan = plan_capabilities("free")

    tier = plan.get("tier", "free")
    overrides: dict[str, Any] = {"tier": tier}
    if tier in {"free", "demo"}:
        overrides["cadence"] = plan.get("temporal_cadence", "seasonal")
        max_history_years = plan.get("max_history_years")
        if max_history_years is not None:
            overrides["max_history_years"] = max_history_years
    return overrides


def _validated_kml_bytes(req: func.HttpRequest, body: Any) -> bytes | func.HttpResponse:
    """Return validated KML bytes or an error response.

    Accepts ``kml_content`` (raw KML), ``coordinates`` (lat/lon text),
    or ``csv_content`` (CSV with lat/lon columns).  Coordinate inputs
    are converted to minimal KML so the rest of the pipeline is unchanged.
    """
    if not isinstance(body, dict):
        return error_response(400, "kml_content, coordinates, or csv_content is required", req=req)

    # --- coordinate text input (#601) ---
    coordinates = body.get("coordinates", "")
    if isinstance(coordinates, str) and coordinates.strip():
        return _coordinates_to_kml(coordinates, body, req)

    # --- CSV input (#601) ---
    csv_content = body.get("csv_content", "")
    if isinstance(csv_content, str) and csv_content.strip():
        return _csv_to_kml(csv_content, body, req)

    # --- classic KML input ---
    kml_content = body.get("kml_content", "")
    if not isinstance(kml_content, str) or not kml_content.strip():
        return error_response(400, "kml_content, coordinates, or csv_content is required", req=req)

    kml_bytes = kml_content.encode("utf-8")
    if len(kml_bytes) > MAX_KML_FILE_SIZE_BYTES:
        return error_response(400, f"KML exceeds {MAX_KML_FILE_SIZE_BYTES} bytes", req=req)

    return kml_bytes


def _coordinates_to_kml(text: str, body: dict, req: func.HttpRequest) -> bytes | func.HttpResponse:
    """Convert coordinate text to KML bytes."""
    from treesight.parsers.coordinate_parser import parse_coordinate_text

    buffer_m = body.get("buffer_m", 500.0)
    if not isinstance(buffer_m, (int, float)) or buffer_m <= 0:
        buffer_m = 500.0

    try:
        features = parse_coordinate_text(text, buffer_m=float(buffer_m))
    except ValueError as exc:
        return error_response(400, str(exc), req=req)

    return _features_to_kml_bytes(features)


def _csv_to_kml(csv_text: str, body: dict, req: func.HttpRequest) -> bytes | func.HttpResponse:
    """Convert CSV text to KML bytes."""
    from treesight.parsers.coordinate_parser import parse_csv

    buffer_m = body.get("buffer_m", 500.0)
    if not isinstance(buffer_m, (int, float)) or buffer_m <= 0:
        buffer_m = 500.0

    try:
        features = parse_csv(csv_text, buffer_m=float(buffer_m))
    except ValueError as exc:
        return error_response(400, str(exc), req=req)

    return _features_to_kml_bytes(features)


def _features_to_kml_bytes(features: list) -> bytes:
    """Convert a list of Feature objects to minimal KML XML bytes."""
    from lxml.etree import Element, SubElement, tostring

    kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = SubElement(kml, "Document")
    SubElement(doc, "name").text = "Coordinate Input"

    for f in features:
        pm = SubElement(doc, "Placemark")
        SubElement(pm, "name").text = f.name
        if f.description:
            SubElement(pm, "description").text = f.description
        polygon = SubElement(pm, "Polygon")
        outer = SubElement(polygon, "outerBoundaryIs")
        lr = SubElement(outer, "LinearRing")
        # KML coordinates: lon,lat,alt separated by whitespace
        coord_str = " ".join(f"{c[0]},{c[1]},0" for c in f.exterior_coords)
        SubElement(lr, "coordinates").text = coord_str

    return tostring(kml, encoding="utf-8", xml_declaration=True)


@bp.route(route="analysis/submit", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
async def analysis_submit(
    req: func.HttpRequest,
) -> func.HttpResponse:
    """POST /api/analysis/submit — signed-in KML submission entry point."""
    if req.method == "OPTIONS":
        return cors_preflight(req)
    return await _submit_analysis_request(req)


def _resolve_quota(
    user_id: str, body: Any, req: func.HttpRequest
) -> tuple[bool, str, func.HttpResponse | None]:
    """Reserve run via org-pooled accounting unless prior upload-token already reserved it.

    Returns ``(reserved, org_id, error_response_or_None)``.
    When the caller already has a verified ticket the run is considered
    reserved via prior_submission_id without a second charge (fixes #767).
    """
    prior_submission_id = body.get("prior_submission_id", "") if isinstance(body, dict) else ""
    if prior_submission_id and _quota_already_consumed(user_id, prior_submission_id):
        logger.info(
            "Skipping reserve — reusing ticket from prior_submission_id=%s user=%s",
            prior_submission_id,
            _redact(user_id),
        )
        try:
            from treesight.storage.client import BlobStorageClient

            storage = BlobStorageClient()
            ticket = storage.download_json(
                DEFAULT_INPUT_CONTAINER, f".tickets/{prior_submission_id}.json"
            )
            org_id = ticket.get("org_id", "")
            return True, org_id, None
        except Exception:
            logger.debug("Could not extract org_id from prior ticket")
            return True, "", None

    try:
        user_org = get_user_org(user_id)
        if not user_org:
            return False, "", error_response(403, "User not in any org", req=req)
        org_id = user_org.get("org_id", "")
    except Exception:
        logger.exception("Org lookup failed for user=%s", _redact(user_id))
        return False, "", error_response(503, "Org lookup unavailable", req=req)

    if not isinstance(org_id, str) or not org_id:
        return False, "", error_response(403, "User not in any org", req=req)

    try:
        reserve_run(
            org_id=org_id,
            user_id=user_id,
            parcel_count=1,
            is_eudr=False,
            instance_id=str(uuid.uuid4()),
        )
        return True, org_id, None
    except MemberCapExceededError:
        return False, org_id, error_response(403, "Member parcel cap exceeded", req=req)
    except QuotaExhaustedError:
        return False, org_id, error_response(403, "Org pool exhausted", req=req)
    except OrgNotFoundError:
        return False, "", error_response(503, "Org not found", req=req)
    except Exception:
        # Transient quota storage errors (e.g. Cosmos unavailable) should not block
        # submission. Allow request to proceed and handle quota accounting later.
        logger.warning(
            "Transient quota reserve failed for org=%s user=%s (continuing with submission)",
            org_id,
            _redact(user_id),
        )
        return True, org_id, None


async def _submit_analysis_request(
    req: func.HttpRequest,
    *,
    blob_prefix: str = "analysis",
) -> func.HttpResponse:
    """Validate, persist, and enqueue a signed-in KML analysis submission."""
    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    # Reject new submissions when the concurrency cap is reached (#759).
    if at_concurrency_cap():
        return func.HttpResponse(
            json.dumps({"error": "Concurrency cap reached — try again later"}),
            status_code=429,
            mimetype="application/json",
            headers={**cors_headers(req), "Retry-After": "30"},
        )

    # Parse body early so we can check for a prior_submission_id before
    # deciding whether to reserve (avoids double-billing on fallback,
    # fixes #767).
    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON body", req=req)

    reserved, org_id, quota_err = _resolve_quota(user_id, body, req)
    if quota_err:
        return quota_err

    submission_context = _extract_submission_context(body)

    effective_provider = submission_context.get("provider_name", DEFAULT_PROVIDER)
    plan_overrides = _submission_plan_overrides(user_id)

    # EUDR mode flag — only accept strict boolean True
    eudr_mode = body.get("eudr_mode") if isinstance(body, dict) else None
    eudr_input: dict[str, Any] = {}
    if eudr_mode is True:
        eudr_input["eudr_mode"] = True
        from treesight.pipeline.submission_helpers import build_eudr_imagery_overrides

        imagery_overrides = build_eudr_imagery_overrides(eudr_mode=True, existing_filters=None)
        if imagery_overrides:
            eudr_input["imagery_filters"] = imagery_overrides

    resp = await _submit_kml(
        req,
        body,
        blob_prefix=blob_prefix,
        extra_input={
            "provider_name": effective_provider,
            "user_id": user_id,
            "org_id": org_id,
            **plan_overrides,
            **eudr_input,
        },
        log_tag=f"Analysis process started prefix={blob_prefix}",
    )

    # If submission failed, refund the reserved parcel.
    if resp.status_code != 202 and reserved and org_id:
        instance_id = body.get("submission_id", "") if isinstance(body, dict) else ""
        if not instance_id:
            instance_id = str(uuid.uuid4())
        _finalize_run_on_failure(org_id, instance_id)

    # Persist submission record for analysis history
    if resp.status_code == 202 and (blob_prefix.strip("/") or "analysis") == "analysis":
        resp_data = json.loads(resp.get_body())
        submission_id = resp_data["instance_id"]
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient()
        from treesight.models.records import RunRecord

        ctx = {k: v for k, v in submission_context.items() if k != "provider_name"}
        run = RunRecord(
            submission_id=submission_id,
            instance_id=submission_id,
            user_id=user_id,
            submitted_at=datetime.now(UTC).isoformat(),
            kml_blob_name=f"{blob_prefix.strip('/') or 'analysis'}/{submission_id}.kml",
            kml_size_bytes=len(body.get("kml_content", "").encode("utf-8"))
            if isinstance(body, dict) and body.get("kml_content")
            else 0,
            submission_prefix=blob_prefix.strip("/") or "analysis",
            provider_name=effective_provider,
            status="submitted",
            eudr_mode=eudr_mode is True,
            **ctx,
        )
        record = run.model_dump(exclude_none=True)
        _persist_submission_record(storage, record, user_id, submission_id)

    return resp


async def _submit_kml(
    req: func.HttpRequest,
    body: Any,
    *,
    blob_prefix: str,
    extra_input: dict[str, Any] | None = None,
    log_tag: str = "",
) -> func.HttpResponse:
    """Validate KML, write ticket, upload blob.

    The orchestrator is started by the Event Grid blob trigger, not here.
    The ticket blob at ``.tickets/{id}.json`` carries user metadata so
    that ``blob_trigger`` can enrich the orchestrator input.
    """
    kml_bytes = _validated_kml_bytes(req, body)
    if isinstance(kml_bytes, func.HttpResponse):
        return kml_bytes

    submission_id = str(uuid.uuid4())
    safe_prefix = blob_prefix.strip("/") or "analysis"
    kml_blob_name = f"{safe_prefix}/{submission_id}.kml"

    from treesight.storage.client import BlobStorageClient

    try:
        storage = BlobStorageClient()

        # Write ticket blob so blob_trigger can read user metadata
        ticket: dict[str, Any] = {
            "created_at": datetime.now(UTC).isoformat(),
        }
        if extra_input:
            ticket.update(extra_input)
        storage.upload_json(
            DEFAULT_INPUT_CONTAINER,
            f".tickets/{submission_id}.json",
            ticket,
        )

        storage.upload_bytes(
            DEFAULT_INPUT_CONTAINER,
            kml_blob_name,
            kml_bytes,
            content_type="application/vnd.google-earth.kml+xml",
        )
    except Exception:
        logger.exception("KML upload failed for %s", kml_blob_name)
        return error_response(
            502,
            "Storage service temporarily unavailable — please retry in a moment.",
            req=req,
        )

    logger.info("%s submission_id=%s blob=%s", log_tag, submission_id, kml_blob_name)

    return func.HttpResponse(
        json.dumps({"instance_id": submission_id, "submission_prefix": safe_prefix}),
        status_code=202,
        mimetype="application/json",
        headers=cors_headers(req),
    )

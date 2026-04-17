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
from treesight.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_PROVIDER, MAX_KML_FILE_SIZE_BYTES
from treesight.security.billing import get_effective_subscription, plan_capabilities
from treesight.security.quota import consume_quota, release_quota

from . import bp
from .history import _extract_submission_context, _persist_submission_record

logger = logging.getLogger(__name__)


def _safe_release_quota(user_id: str) -> None:
    """Best-effort quota refund — never raises."""
    try:
        release_quota(user_id)
    except Exception:
        logger.exception("Failed to release quota for user=%s", user_id)


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

    # Consume quota upfront (atomic reservation).  If storage is
    # transiently unavailable we log the error but still allow the
    # submission so a temporary outage doesn't block users.
    quota_consumed = False
    billing_fields: dict[str, Any] = {}
    try:
        consume_quota(user_id)
        quota_consumed = True
        # Classify the run for the billing ledger (#589).
        try:
            from treesight.security.billing_ledger import billing_fields_for_submission

            billing_fields = billing_fields_for_submission(user_id)
        except Exception:
            logger.warning("Billing classification failed for user=%s", user_id, exc_info=True)
    except ValueError as exc:
        # Quota genuinely exhausted — hard block.
        return error_response(403, str(exc), req=req)
    except Exception:
        logger.exception("Quota storage unavailable for user=%s — allowing submission", user_id)

    try:
        body = req.get_json()
    except ValueError:
        if quota_consumed:
            _safe_release_quota(user_id)
        return error_response(400, "Invalid JSON body", req=req)

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
            **plan_overrides,
            **eudr_input,
        },
        log_tag=f"Analysis process started prefix={blob_prefix}",
    )

    # If submission failed, refund the quota slot we consumed upfront.
    if resp.status_code != 202 and quota_consumed:
        _safe_release_quota(user_id)

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
            **billing_fields,
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

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
from treesight.parsers import count_kml_features, maybe_unzip
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
    """Return validated KML bytes or an error response."""
    kml_content = body.get("kml_content", "") if isinstance(body, dict) else ""
    if not isinstance(kml_content, str) or not kml_content.strip():
        return error_response(400, "kml_content is required", req=req)

    kml_bytes = kml_content.encode("utf-8")
    if len(kml_bytes) > MAX_KML_FILE_SIZE_BYTES:
        return error_response(400, f"KML exceeds {MAX_KML_FILE_SIZE_BYTES} bytes", req=req)

    return kml_bytes


def _check_aoi_limit(
    kml_bytes: bytes, tier: str, req: func.HttpRequest
) -> func.HttpResponse | None:
    """Return an error response if the KML exceeds the tier's AOI limit, else None."""
    try:
        raw_kml = maybe_unzip(kml_bytes)
        feature_count = count_kml_features(raw_kml)
    except ValueError:
        return None  # let the pipeline's full parser handle errors

    aoi_limit = plan_capabilities(tier).get("aoi_limit")
    if aoi_limit is not None and feature_count > aoi_limit:
        tier_label = plan_capabilities(tier).get("label", tier)
        return error_response(
            403,
            f"This file contains {feature_count} parcels but your "
            f"{tier_label} plan allows {aoi_limit} per submission. "
            f"Upgrade your plan or reduce the number of parcels.",
            req=req,
        )
    return None


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
    try:
        consume_quota(user_id)
        quota_consumed = True
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

    # --- AOI limit enforcement (§ #575) ---
    kml_bytes = _validated_kml_bytes(req, body)
    if isinstance(kml_bytes, func.HttpResponse):
        if quota_consumed:
            _safe_release_quota(user_id)
        return kml_bytes

    tier = plan_overrides.get("tier", "free")
    aoi_err = _check_aoi_limit(kml_bytes, tier, req)
    if aoi_err is not None:
        if quota_consumed:
            _safe_release_quota(user_id)
        return aoi_err

    resp = await _submit_kml(
        req,
        body,
        blob_prefix=blob_prefix,
        extra_input={
            "provider_name": effective_provider,
            "user_id": user_id,
            **plan_overrides,
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
        record: dict[str, Any] = {
            "submission_id": submission_id,
            "instance_id": submission_id,
            "user_id": user_id,
            "submitted_at": datetime.now(UTC).isoformat(),
            "kml_blob_name": f"{blob_prefix.strip('/') or 'analysis'}/{submission_id}.kml",
            "kml_size_bytes": len(body.get("kml_content", "").encode("utf-8"))
            if isinstance(body, dict)
            else 0,
            "submission_prefix": blob_prefix.strip("/") or "analysis",
            "provider_name": effective_provider,
            "status": "submitted",
        }
        record.update(submission_context)
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

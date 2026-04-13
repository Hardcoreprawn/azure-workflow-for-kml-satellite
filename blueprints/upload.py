"""Upload BFF endpoints — SAS minting and status polling.

These endpoints serve the user-interactive upload flow.
They are lightweight reads/writes that keep the BFF responsive while
the pipeline runs asynchronously on Container Apps.

NOTE: Do NOT add ``from __future__ import annotations`` to blueprint modules.
The Azure Functions worker inspects function signatures at import time
and ``from __future__ import annotations`` turns all annotations into
strings, which breaks binding resolution.
"""

import datetime
import json
import logging
import uuid

import azure.functions as func
from azure.storage.blob import (
    BlobSasPermissions,
    ContentSettings,
    generate_blob_sas,
)

from treesight.config import STORAGE_ACCOUNT_NAME
from treesight.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_PROVIDER, MAX_KML_FILE_SIZE_BYTES
from treesight.security.quota import consume_quota, release_quota
from treesight.storage import cosmos as _cosmos_mod
from treesight.storage.client import get_blob_service_client

from ._helpers import cors_headers, error_response, require_auth

logger = logging.getLogger(__name__)

bp = func.Blueprint()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SAS_TOKEN_EXPIRY_MINUTES = 15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _persist_submission_record(submission_id: str, record: dict, user_id: str) -> None:
    """Write a submission record so the run appears in analysis history."""
    if _cosmos_mod.cosmos_available():
        try:
            _cosmos_mod.upsert_item("runs", {"id": submission_id, **record})
            return
        except Exception:
            logger.warning(
                "Cosmos upsert failed for instance=%s user=%s",
                submission_id,
                user_id,
                exc_info=True,
            )

    # Blob fallback
    from treesight.constants import PIPELINE_PAYLOADS_CONTAINER
    from treesight.storage.client import BlobStorageClient

    try:
        storage = BlobStorageClient()
        blob_name = f"analysis-submissions/{user_id}/{submission_id}.json"
        storage.upload_json(PIPELINE_PAYLOADS_CONTAINER, blob_name, record)
    except Exception:
        logger.warning(
            "Unable to persist submission record instance=%s user=%s",
            submission_id,
            user_id,
            exc_info=True,
        )


def _sanitise_submission_context(ctx: dict) -> dict:
    """Allow-list filter for submission context fields."""
    clean: dict = {}
    for field in ("feature_count", "aoi_count"):
        value = ctx.get(field)
        if isinstance(value, (int, float)) and value >= 0:
            clean[field] = int(value)
    for field in ("max_spread_km", "total_area_ha", "largest_area_ha"):
        value = ctx.get(field)
        if isinstance(value, (int, float)) and value >= 0:
            clean[field] = round(float(value), 2)
    for field in ("processing_mode", "provider_name", "workspace_role", "workspace_preference"):
        value = ctx.get(field)
        if isinstance(value, str) and value.strip():
            clean[field] = value.strip()[:80]
    return clean


# ---------------------------------------------------------------------------
# POST /api/upload/token — mint a time-limited, write-only SAS URL
# ---------------------------------------------------------------------------


def _safe_release_quota(user_id: str, instance_id: str = "") -> None:
    """Best-effort quota refund — never raises."""
    try:
        release_quota(user_id, instance_id=instance_id)
    except Exception:
        logger.exception("Failed to release quota for user=%s", user_id)


def _mint_sas_url(
    blob_service,
    blob_name: str,
    submission_id: str,
) -> tuple[str | None, str | None]:
    """Generate a write-only SAS URL. Returns (sas_url, error_msg)."""
    now = datetime.datetime.now(datetime.UTC)
    expiry = now + datetime.timedelta(minutes=_SAS_TOKEN_EXPIRY_MINUTES)

    delegation_key = blob_service.get_user_delegation_key(
        key_start_time=now,
        key_expiry_time=expiry,
    )

    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=DEFAULT_INPUT_CONTAINER,
        blob_name=blob_name,
        user_delegation_key=delegation_key,
        permission=BlobSasPermissions(create=True, write=True),
        expiry=expiry,
        content_type="application/vnd.google-earth.kml+xml",
    )

    sas_url = (
        f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/"
        f"{DEFAULT_INPUT_CONTAINER}/{blob_name}?{sas_token}"
    )
    return sas_url, None


def _resolve_provider(body: dict, submission_context: dict) -> str:
    """Pick the effective provider from request body, falling back to submission context."""
    top_level = body.get("provider_name")
    if isinstance(top_level, str) and top_level.strip():
        return top_level.strip()[:80]
    return submission_context.get("provider_name", DEFAULT_PROVIDER)


@bp.route(route="upload/token", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def upload_token(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Mint a write-only SAS URL for direct-to-blob KML upload."""
    if not user_id:
        return error_response(401, "Missing user identity", req=req)

    if not STORAGE_ACCOUNT_NAME:
        logger.error("Storage account not configured for SAS generation")
        return error_response(503, "Service not configured", req=req)

    # Consume quota upfront so the runs counter decrements immediately.
    quota_consumed = False
    try:
        consume_quota(user_id)
        quota_consumed = True
    except ValueError as exc:
        return error_response(403, str(exc), req=req)
    except Exception:
        logger.exception("Quota storage unavailable for user=%s — allowing submission", user_id)

    submission_id = str(uuid.uuid4())
    blob_name = f"analysis/{submission_id}.kml"

    # Parse optional submission context from request body
    try:
        body = json.loads(req.get_body()) if req.get_body() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}

    submission_context = _sanitise_submission_context(body.get("submission_context") or {})
    effective_provider = _resolve_provider(body, submission_context)

    # Write ticket blob — trusted server-side record of who initiated the upload
    ticket: dict = {
        "user_id": user_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    provider = body.get("provider_name")
    if isinstance(provider, str) and provider.strip():
        ticket["provider_name"] = provider.strip()[:80]
    if submission_context:
        ticket["submission_context"] = submission_context

    try:
        blob_service = get_blob_service_client()
        ticket_blob = blob_service.get_blob_client(
            DEFAULT_INPUT_CONTAINER, f".tickets/{submission_id}.json"
        )
        ticket_blob.upload_blob(
            json.dumps(ticket).encode(),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
    except Exception:
        logger.exception("Failed to write ticket for submission_id=%s", submission_id)
        if quota_consumed:
            _safe_release_quota(user_id, instance_id=submission_id)
        return error_response(502, "Storage service temporarily unavailable", req=req)

    try:
        sas_url, _ = _mint_sas_url(blob_service, blob_name, submission_id)
    except Exception:
        logger.exception("Failed to mint SAS URL for submission_id=%s", submission_id)
        if quota_consumed:
            _safe_release_quota(user_id, instance_id=submission_id)
        return error_response(502, "Storage service temporarily unavailable", req=req)

    # Persist submission record only after SAS minting succeeds
    # so a minting failure doesn't leave a phantom run.
    submitted_at = datetime.datetime.now(datetime.UTC).isoformat()
    record: dict = {
        "submission_id": submission_id,
        "instance_id": submission_id,
        "user_id": user_id,
        "submitted_at": submitted_at,
        "kml_blob_name": blob_name,
        "kml_size_bytes": 0,
        "submission_prefix": "analysis",
        "provider_name": effective_provider,
        "status": "submitted",
    }
    record.update(submission_context)
    _persist_submission_record(submission_id, record, user_id)

    logger.info("Upload URL minted submission_id=%s blob=%s", submission_id, blob_name)

    return func.HttpResponse(
        json.dumps(
            {
                "submissionId": submission_id,
                "sasUrl": sas_url,
                "blobName": blob_name,
                "container": DEFAULT_INPUT_CONTAINER,
                "expiresMinutes": _SAS_TOKEN_EXPIRY_MINUTES,
                "maxBytes": MAX_KML_FILE_SIZE_BYTES,
            }
        ),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )


# ---------------------------------------------------------------------------
# GET /api/upload/status/{submission_id} — poll orchestration status
# ---------------------------------------------------------------------------


@bp.route(
    route="upload/status/{submission_id}",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def upload_status(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Poll the status of a pipeline submission from Cosmos."""
    if not user_id:
        return error_response(401, "Missing user identity", req=req)

    submission_id = req.route_params.get("submission_id", "")
    if not submission_id:
        return error_response(400, "Missing submission_id", req=req)

    # Validate UUID format to prevent injection
    try:
        uuid.UUID(submission_id)
    except ValueError:
        return error_response(400, "Invalid submission_id format", req=req)

    # Read status from Cosmos runs container
    try:
        records = _cosmos_mod.query_items(
            "runs",
            "SELECT c.submission_id, c.status, c.submitted_at, c.feature_count,"
            " c.aoi_count FROM c WHERE c.submission_id = @sid",
            parameters=[{"name": "@sid", "value": submission_id}],
        )
    except Exception:
        logger.exception("Cosmos query failed for submission_id=%s", submission_id)
        return error_response(503, "Status temporarily unavailable", req=req)

    if records:
        record = records[0]
        return func.HttpResponse(
            json.dumps(
                {
                    "submissionId": submission_id,
                    "status": record.get("status", "pending"),
                    "submittedAt": record.get("submitted_at", ""),
                    "featureCount": record.get("feature_count"),
                    "aoiCount": record.get("aoi_count"),
                }
            ),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers(req),
        )

    # Not found yet — may still be in the ingestion queue
    return func.HttpResponse(
        json.dumps(
            {
                "submissionId": submission_id,
                "status": "pending",
                "message": "Submission is being processed",
            }
        ),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )

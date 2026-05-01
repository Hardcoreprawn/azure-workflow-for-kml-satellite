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
from treesight.security.eudr_billing import check_eudr_entitlement, consume_eudr_trial
from treesight.security.orgs import get_user_org
from treesight.security.quota import consume_quota, release_quota
from treesight.security.redact import redact_user_id as _redact
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


_KMZ_EXTENSION = ".kmz"
_KML_EXTENSION = ".kml"
_KMZ_CONTENT_TYPE = "application/vnd.google-earth.kmz"
_KML_CONTENT_TYPE = "application/vnd.google-earth.kml+xml"


def _detect_file_extension(filename: str) -> tuple[str, str]:
    """Return (extension, content_type) from a client-supplied filename.

    Only .kml and .kmz are accepted.  Any other value (including empty string)
    falls back to .kml so the pipeline is never silently broken by a bad client.
    Detection is case-insensitive.
    """
    if isinstance(filename, str) and filename.lower().endswith(_KMZ_EXTENSION):
        return _KMZ_EXTENSION, _KMZ_CONTENT_TYPE
    return _KML_EXTENSION, _KML_CONTENT_TYPE


def _mint_sas_url(
    blob_service,
    blob_name: str,
    submission_id: str,
    content_type: str = _KML_CONTENT_TYPE,
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
        content_type=content_type,
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


def _build_ticket(body: dict, user_id: str, submission_context: dict) -> dict:
    """Assemble the ticket blob payload from request body and user metadata."""
    ticket: dict = {
        "user_id": user_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    provider = body.get("provider_name")
    if isinstance(provider, str) and provider.strip():
        ticket["provider_name"] = provider.strip()[:80]
    if submission_context:
        ticket["submission_context"] = submission_context

    # EUDR mode flag — only accept strict boolean True
    if body.get("eudr_mode") is True:
        ticket["eudr_mode"] = True
        from treesight.pipeline.submission_helpers import build_eudr_imagery_overrides

        imagery_overrides = build_eudr_imagery_overrides(eudr_mode=True, existing_filters=None)
        if imagery_overrides:
            ticket["imagery_filters"] = imagery_overrides

    return ticket


def _check_eudr_entitlement(
    user_id: str, req: func.HttpRequest
) -> tuple[str, dict, func.HttpResponse | None]:
    """Validate EUDR entitlement for the requesting user's org.

    Returns (org_id, entitlement_dict, error_response_or_None).
    """
    try:
        org = get_user_org(user_id)
    except Exception:
        logger.exception(
            "Failed to resolve org for EUDR entitlement",
            extra={"user_id": _redact(user_id)},
        )
        return (
            "",
            {},
            error_response(
                503,
                "Unable to verify EUDR entitlement right now. Please retry shortly.",
                req=req,
            ),
        )
    if not org:
        return (
            "",
            {},
            error_response(
                403,
                "EUDR assessments require an org. Create or join an org first.",
                req=req,
            ),
        )
    org_id = org["org_id"]
    try:
        entitlement = check_eudr_entitlement(org_id)
    except Exception:
        logger.exception(
            "EUDR entitlement check failed during upload flow",
            extra={"org_id": org_id, "user_id": _redact(user_id)},
        )
        return (
            org_id,
            {},
            error_response(
                503,
                "EUDR entitlement service is temporarily unavailable. Please retry.",
                req=req,
            ),
        )
    if not entitlement["allowed"]:
        return (
            org_id,
            entitlement,
            error_response(
                403,
                "EUDR entitlement exhausted — subscription required",
                req=req,
            ),
        )
    return org_id, entitlement, None


def _consume_upload_quota(
    user_id: str, req: func.HttpRequest
) -> tuple[bool, dict, func.HttpResponse | None]:
    """Consume quota and compute billing fields.

    Returns (quota_consumed, billing_fields, error_response_or_None).
    """
    billing_fields: dict = {}
    try:
        consume_quota(user_id)
    except ValueError as exc:
        return False, {}, error_response(403, str(exc), req=req)
    except Exception:
        logger.exception(
            "Quota storage unavailable for user=%s — allowing submission",
            _redact(user_id),
        )
        return False, {}, None

    try:
        from treesight.security.billing_ledger import billing_fields_for_submission

        billing_fields = billing_fields_for_submission(user_id)
    except Exception:
        logger.warning("Billing classification failed for user=%s", user_id, exc_info=True)

    return True, billing_fields, None


def _write_ticket_and_mint_sas(
    body: dict,
    user_id: str,
    submission_id: str,
    blob_name: str,
    submission_context: dict,
    quota_consumed: bool,
    req: func.HttpRequest,
    content_type: str = _KML_CONTENT_TYPE,
) -> tuple[str | None, func.HttpResponse | None]:
    """Write ticket blob and mint SAS URL.

    Returns (sas_url, error_response_or_None).
    """
    ticket = _build_ticket(body, user_id, submission_context)
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
        return None, error_response(502, "Storage service temporarily unavailable", req=req)

    try:
        sas_url, _ = _mint_sas_url(blob_service, blob_name, submission_id, content_type)
    except Exception:
        logger.exception("Failed to mint SAS URL for submission_id=%s", submission_id)
        if quota_consumed:
            _safe_release_quota(user_id, instance_id=submission_id)
        return None, error_response(502, "Storage service temporarily unavailable", req=req)

    return sas_url, None


def _consume_eudr_trial_if_needed(
    is_eudr: bool,
    entitlement: dict,
    eudr_org_id: str,
    quota_consumed: bool,
    user_id: str,
    submission_id: str,
    req: func.HttpRequest,
) -> func.HttpResponse | None:
    """Decrement EUDR free-trial counter if applicable.

    Returns error_response or None on success.
    """
    if not (is_eudr and entitlement.get("reason") == "free_trial"):
        return None
    try:
        consume_eudr_trial(eudr_org_id)
    except ValueError:
        logger.warning(
            "EUDR trial race: entitlement passed but consume failed org=%s",
            eudr_org_id,
        )
        if quota_consumed:
            _safe_release_quota(user_id, instance_id=submission_id)
        return error_response(
            403,
            "EUDR entitlement exhausted — subscription required",
            req=req,
        )
    except Exception:
        logger.exception(
            "EUDR trial consumption failed unexpectedly org=%s",
            eudr_org_id,
        )
        if quota_consumed:
            _safe_release_quota(user_id, instance_id=submission_id)
        return error_response(
            503,
            "EUDR entitlement service is temporarily unavailable. Please retry.",
            req=req,
        )
    return None


@bp.route(route="upload/token", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def upload_token(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Mint a write-only SAS URL for direct-to-blob KML upload."""
    if not user_id:
        return error_response(401, "Missing user identity", req=req)

    if not STORAGE_ACCOUNT_NAME:
        logger.error("Storage account not configured for SAS generation")
        return error_response(503, "Service not configured", req=req)

    # Parse request body early — needed for EUDR entitlement check.
    try:
        body = json.loads(req.get_body()) if req.get_body() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}

    is_eudr = body.get("eudr_mode") is True

    # ── EUDR entitlement gate ──────────────────────────────────────
    eudr_org_id: str = ""
    entitlement: dict = {}
    if is_eudr:
        eudr_org_id, entitlement, err = _check_eudr_entitlement(user_id, req)
        if err:
            return err

    # Consume quota upfront so the runs counter decrements immediately.
    quota_consumed, billing_fields, quota_err = _consume_upload_quota(user_id, req)
    if quota_err:
        return quota_err

    submission_id = str(uuid.uuid4())
    ext, content_type = _detect_file_extension(body.get("filename", ""))
    blob_name = f"analysis/{submission_id}{ext}"

    submission_context = _sanitise_submission_context(body.get("submission_context") or {})
    effective_provider = _resolve_provider(body, submission_context)

    # Write ticket blob + mint SAS URL
    sas_url, storage_err = _write_ticket_and_mint_sas(
        body,
        user_id,
        submission_id,
        blob_name,
        submission_context,
        quota_consumed,
        req,
        content_type,
    )
    if storage_err:
        return storage_err

    # ── EUDR trial consumption ─────────────────────────────────────
    eudr_err = _consume_eudr_trial_if_needed(
        is_eudr,
        entitlement,
        eudr_org_id,
        quota_consumed,
        user_id,
        submission_id,
        req,
    )
    if eudr_err:
        return eudr_err

    # Persist submission record only after SAS minting succeeds
    submitted_at = datetime.datetime.now(datetime.UTC).isoformat()
    from treesight.models.records import RunRecord

    ctx = {k: v for k, v in submission_context.items() if k != "provider_name"}
    run = RunRecord(
        submission_id=submission_id,
        instance_id=submission_id,
        user_id=user_id,
        submitted_at=submitted_at,
        kml_blob_name=blob_name,
        kml_size_bytes=0,
        submission_prefix="analysis",
        provider_name=effective_provider,
        status="submitted",
        eudr_mode=body.get("eudr_mode") is True,
        **ctx,
        **billing_fields,
    )
    _persist_submission_record(submission_id, run.model_dump(exclude_none=True), user_id)

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

    # Read status from Cosmos runs container (scoped to authenticated user)
    try:
        records = _cosmos_mod.query_items(
            "runs",
            "SELECT c.submission_id, c.status, c.submitted_at, c.feature_count,"
            " c.aoi_count FROM c WHERE c.submission_id = @sid"
            " AND c.user_id = @uid",
            parameters=[
                {"name": "@sid", "value": submission_id},
                {"name": "@uid", "value": user_id},
            ],
            partition_key=user_id,
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

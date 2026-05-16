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

from treesight.billing.accounting import (
    MemberCapExceededError,
    OrgNotFoundError,
    QuotaExhaustedError,
    reserve_run,
)
from treesight.config import STORAGE_ACCOUNT_NAME
from treesight.constants import DEFAULT_INPUT_CONTAINER, DEFAULT_PROVIDER, MAX_KML_FILE_SIZE_BYTES
from treesight.security.orgs import create_org, get_user_org
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


_KMZ_EXTENSION = ".kmz"
_KML_EXTENSION = ".kml"
_KMZ_CONTENT_TYPE = "application/vnd.google-earth.kmz"
_KML_CONTENT_TYPE = "application/vnd.google-earth.kml+xml"


def _detect_file_extension(filename: str) -> tuple[str, str]:
    """Return (extension, content_type) from a client-supplied filename.

    Accepts .kml and .kmz; any other value (including empty string) falls back
    to .kml so the pipeline is never silently broken by a bad client.
    Detection is case-insensitive.

    KMZ blobs are decompressed server-side by ``maybe_unzip`` in the ingestion
    activity, which also enforces zip-bomb and compression-ratio limits.
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
    """Generate a write-only SAS URL. Returns (sas_url, error_msg).

    The ``content_type`` value is embedded in the SAS token as a response-header
    override (``rsct``).  It controls the ``Content-Type`` header returned when
    the blob is *downloaded* via the SAS URL, but does **not** automatically set
    the blob's stored Content-Type.  Callers that need the blob stored with the
    correct Content-Type must include ``Content-Type`` (or the Azure-specific
    ``x-ms-blob-content-type``) header on the client-side PUT request.  The
    upload-token response includes ``contentType`` so the client can do this.
    """
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


def _build_ticket(body: dict, user_id: str, submission_context: dict, org_id: str = "") -> dict:
    """Assemble the ticket blob payload from request body and user metadata."""
    ticket: dict = {
        "user_id": user_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    if org_id:
        ticket["org_id"] = org_id
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


def _write_ticket_and_mint_sas(
    body: dict,
    user_id: str,
    submission_id: str,
    blob_name: str,
    submission_context: dict,
    req: func.HttpRequest,
    org_id: str = "",
    content_type: str = _KML_CONTENT_TYPE,
) -> tuple[str | None, func.HttpResponse | None]:
    """Write ticket blob and mint SAS URL.

    Returns (sas_url, error_response_or_None).
    """
    ticket = _build_ticket(body, user_id, submission_context, org_id=org_id)
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
        return None, error_response(502, "Storage service temporarily unavailable", req=req)

    try:
        sas_url, _ = _mint_sas_url(
            blob_service, blob_name, submission_id, content_type=content_type
        )
    except Exception:
        logger.exception("Failed to mint SAS URL for submission_id=%s", submission_id)
        return None, error_response(502, "Storage service temporarily unavailable", req=req)

    return sas_url, None


def _reserve_run_or_error(
    org_id: str,
    user_id: str,
    parcel_count: int,
    is_eudr: bool,
    submission_id: str,
    req: func.HttpRequest,
) -> func.HttpResponse | None:
    """Attempt to reserve a run. Returns an error response on failure, None on success."""
    try:
        reserve_run(
            org_id=org_id,
            user_id=user_id,
            parcel_count=parcel_count,
            is_eudr=is_eudr,
            instance_id=submission_id,
        )
    except MemberCapExceededError as exc:
        logger.info(
            "Member cap exceeded during reservation org=%s user=%s", org_id, _redact(user_id)
        )
        return error_response(403, f"Your parcel capacity is exceeded. {exc!s}", req=req)
    except QuotaExhaustedError as exc:
        logger.info("Organization quota exhausted during reservation org=%s", org_id)
        return error_response(403, f"Organization parcel quota exhausted. {exc!s}", req=req)
    except OrgNotFoundError:
        logger.warning("Org not found during reservation org=%s", org_id)
        return error_response(503, "Organization not found. Please try again.", req=req)
    except Exception:
        logger.exception("Run reservation failed unexpectedly org=%s", org_id)
        return error_response(503, "Unable to process reservation. Please try again.", req=req)
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

    # ── Org-pooled run accounting (reserve_run) ────────────────────
    try:
        user_org = get_user_org(user_id)
    except Exception:
        logger.exception(
            "Failed to resolve org for run reservation",
            extra={"user_id": _redact(user_id)},
        )
        return error_response(
            503, "Unable to reserve runs right now. Please retry shortly.", req=req
        )

    if not user_org:
        # Auto-create a personal org so existing users aren't blocked.
        # They can rename or share it from the account dashboard.
        try:
            from treesight.security.users import get_user

            user_doc = get_user(user_id) or {}
            email = user_doc.get("email", "")
            display_name = user_doc.get("display_name", "")
            org_name = f"{display_name}'s Organisation" if display_name else "My Organisation"
            user_org = create_org(user_id, name=org_name, email=email)
            logger.info(
                "Auto-created personal org for user=%s org_id=%s",
                _redact(user_id),
                user_org["org_id"],
            )
        except Exception:
            logger.exception("Failed to auto-create org for user=%s", _redact(user_id))
            return error_response(
                503,
                "Unable to set up your organisation. Please try again or contact support.",
                req=req,
            )

    org_id = user_org["org_id"]
    submission_id = str(uuid.uuid4())
    parcel_count = body.get("parcel_count", 1)  # Default to 1 if not provided

    reservation_err = _reserve_run_or_error(
        org_id, user_id, parcel_count, is_eudr, submission_id, req
    )
    if reservation_err:
        return reservation_err

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
        req,
        org_id=org_id,
        content_type=content_type,
    )
    if storage_err:
        # On error, we need to release the reservation
        try:
            from treesight.billing.accounting import finalize_run

            finalize_run(org_id=org_id, instance_id=submission_id, status="failed")
        except Exception:
            logger.exception(
                "Failed to refund reservation after storage error org=%s instance=%s",
                org_id,
                submission_id,
            )
        return storage_err

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
                "contentType": content_type,
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

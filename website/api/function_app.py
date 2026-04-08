"""SWA managed API functions — lightweight, always-warm endpoints.

These functions run inside the Static Web App's managed function runtime.
They handle user-interactive requests (SAS token minting, status polling)
so the main Container Apps function app can scale to zero without affecting UX.

Authentication is handled by the SWA platform using built-in custom auth
(Azure AD / Entra External ID).  SWA injects user identity via the
``x-ms-client-principal`` header — a Base64-encoded JSON payload containing
``identityProvider``, ``userId``, ``userDetails``, and ``userRoles``.

Environment variables (set via SWA app_settings in OpenTofu):
  STORAGE_ACCOUNT_NAME   — storage account for SAS token generation
  SAS_TOKEN_EXPIRY_MINUTES — SAS token lifetime (default: 15)

Authentication to Azure Storage uses the SWA's system-assigned managed
identity (DefaultAzureCredential) — no shared secrets.
"""

from __future__ import annotations

import base64
import datetime
import json
import logging
import os
import uuid

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)

app = func.FunctionApp()
logger = logging.getLogger("swa-api")

# ---------------------------------------------------------------------------
# Configuration (read once at cold-start)
# ---------------------------------------------------------------------------

STORAGE_ACCOUNT_NAME = os.environ.get("STORAGE_ACCOUNT_NAME", "")
INPUT_CONTAINER = os.environ.get("INPUT_CONTAINER", "kml-input")
SAS_TOKEN_EXPIRY_MINUTES = int(os.environ.get("SAS_TOKEN_EXPIRY_MINUTES", "15"))
MAX_UPLOAD_BYTES = 10_485_760  # 10 MiB — matches treesight MAX_KML_FILE_SIZE_BYTES

# Cosmos DB (for billing/status, analysis/history)
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "")
COSMOS_DATABASE_NAME = os.environ.get("COSMOS_DATABASE_NAME", "canopex")

_blob_service: BlobServiceClient | None = None
_cosmos_db: object | None = None  # Azure Cosmos DatabaseProxy


def _get_blob_service() -> BlobServiceClient:
    """Lazy-init BlobServiceClient with managed identity credential."""
    global _blob_service
    if _blob_service is None:
        if not STORAGE_ACCOUNT_NAME:
            raise RuntimeError("STORAGE_ACCOUNT_NAME is not configured")
        account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
        _blob_service = BlobServiceClient(
            account_url=account_url,
            credential=DefaultAzureCredential(),
        )
    return _blob_service


def _get_cosmos_container(container_name: str):
    """Return a Cosmos DB container proxy, lazily initialising the database client."""
    global _cosmos_db
    if _cosmos_db is None:
        if not COSMOS_ENDPOINT:
            raise RuntimeError("COSMOS_ENDPOINT is not configured")
        from azure.cosmos import CosmosClient

        client = CosmosClient(COSMOS_ENDPOINT, credential=DefaultAzureCredential())
        _cosmos_db = client.get_database_client(COSMOS_DATABASE_NAME)
    return _cosmos_db.get_container_client(container_name)


def _parse_client_principal(req: func.HttpRequest) -> dict:
    """Extract user identity from the SWA ``x-ms-client-principal`` header.

    Returns a dict with ``userId``, ``userDetails``, ``identityProvider``,
    ``userRoles``, and a ``sub`` alias (for compatibility with code that
    reads ``claims["sub"]``).

    Raises ``ValueError`` when the header is missing or malformed.
    """
    raw = req.headers.get("x-ms-client-principal", "")
    if not raw:
        raise ValueError("Missing x-ms-client-principal header")

    try:
        decoded = base64.b64decode(raw)
        principal = json.loads(decoded)
    except Exception as exc:
        raise ValueError(f"Malformed client principal: {exc}") from exc

    user_id: str = principal.get("userId", "")
    if not user_id:
        raise ValueError("Client principal missing userId")

    # Provide 'sub' alias so callers can use claims["sub"] unchanged
    principal["sub"] = user_id
    return principal


def _error(status: int, message: str, *, reason: str = "") -> func.HttpResponse:
    """Return a JSON error response."""
    body: dict = {"error": message}
    if reason:
        body["reason"] = reason
    return func.HttpResponse(
        json.dumps(body),
        status_code=status,
        mimetype="application/json",
    )


def _sanitise_submission_context(ctx: dict) -> dict:
    """Allow-list filter for submission_context — mirrors _extract_submission_context."""
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


def _json_response(data: dict, status: int = 200) -> func.HttpResponse:
    """Return a JSON success response."""
    return func.HttpResponse(
        json.dumps(data),
        status_code=status,
        mimetype="application/json",
    )


# ---------------------------------------------------------------------------
# POST /api/upload/token — mint a time-limited, write-only SAS URL
# ---------------------------------------------------------------------------


@app.function_name("upload_token")
@app.route(route="upload/token", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def upload_token(req: func.HttpRequest) -> func.HttpResponse:
    """Mint a write-only SAS URL for direct-to-blob KML upload.

    Requires a valid CIAM JWT in the Authorization header.
    Returns a pre-signed URL scoped to a single blob in kml-input/.
    """
    # --- auth (SWA built-in — x-ms-client-principal) ---
    try:
        claims = _parse_client_principal(req)
    except ValueError as exc:
        logger.warning("Upload auth failed: %s", exc)
        return _error(401, "Unauthorized")

    user_id = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    # --- config check ---
    if not STORAGE_ACCOUNT_NAME:
        logger.error("Storage account not configured for SAS generation")
        return _error(503, "Service not configured")

    # --- mint SAS ---
    # NOTE: Quota enforcement is handled by the Container Apps submission
    # endpoint (submission.py).  The SWA API path bypasses quota because
    # this module deliberately avoids importing treesight.  Slice 4 will
    # add quota checking to blob_trigger so both paths are gated.
    submission_id = str(uuid.uuid4())
    blob_name = f"analysis/{submission_id}.kml"

    # --- parse optional submission context ---
    try:
        body = json.loads(req.get_body()) if req.get_body() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}

    # --- write ticket blob (trusted server-side record) ---
    ticket: dict = {
        "user_id": user_id,
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    provider = body.get("provider_name")
    if isinstance(provider, str) and provider.strip():
        ticket["provider_name"] = provider.strip()[:80]
    ctx = body.get("submission_context")
    if isinstance(ctx, dict):
        ticket["submission_context"] = _sanitise_submission_context(ctx)

    try:
        blob_service = _get_blob_service()
        ticket_blob = blob_service.get_blob_client(
            INPUT_CONTAINER, f".tickets/{submission_id}.json"
        )
        ticket_blob.upload_blob(
            json.dumps(ticket).encode(),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
    except Exception:
        logger.exception("Failed to write ticket for submission_id=%s", submission_id)
        return _error(502, "Storage service temporarily unavailable")

    now = datetime.datetime.now(datetime.UTC)
    expiry = now + datetime.timedelta(minutes=SAS_TOKEN_EXPIRY_MINUTES)

    try:
        delegation_key = blob_service.get_user_delegation_key(
            key_start_time=now,
            key_expiry_time=expiry,
        )
    except Exception:
        logger.exception("Failed to obtain user delegation key")
        return _error(502, "Storage service temporarily unavailable")

    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=INPUT_CONTAINER,
        blob_name=blob_name,
        user_delegation_key=delegation_key,
        permission=BlobSasPermissions(create=True, write=True),
        expiry=expiry,
        content_type="application/vnd.google-earth.kml+xml",
    )

    sas_url = (
        f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/"
        f"{INPUT_CONTAINER}/{blob_name}?{sas_token}"
    )

    logger.info(
        "Upload URL minted submission_id=%s blob=%s",
        submission_id,
        blob_name,
    )

    return _json_response(
        {
            "submission_id": submission_id,
            "sas_url": sas_url,
            "blob_name": blob_name,
            "container": INPUT_CONTAINER,
            "expires_minutes": SAS_TOKEN_EXPIRY_MINUTES,
            "max_bytes": MAX_UPLOAD_BYTES,
        },
        status=200,
    )


# ---------------------------------------------------------------------------
# GET /api/upload/status/{submission_id} — poll orchestration status
# ---------------------------------------------------------------------------


@app.function_name("upload_status")
@app.route(
    route="upload/status/{submission_id}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def upload_status(req: func.HttpRequest) -> func.HttpResponse:
    """Poll the status of a pipeline submission.

    Proxies to the Durable Functions status endpoint on the Container Apps
    function app.  This keeps the status-polling path always-warm via SWA
    while the heavy pipeline work runs on Container Apps.
    """
    # --- auth (SWA built-in — x-ms-client-principal) ---
    try:
        _parse_client_principal(req)
    except ValueError as exc:
        logger.warning("Status auth failed: %s", exc)
        return _error(401, "Unauthorized")

    submission_id = req.route_params.get("submission_id", "")
    if not submission_id:
        return _error(400, "Missing submission_id")

    # Validate UUID format to prevent injection
    try:
        uuid.UUID(submission_id)
    except ValueError:
        return _error(400, "Invalid submission_id format")

    # For now, return a placeholder — the full implementation will read
    # from Cosmos DB or proxy to the Durable Functions status API.
    # This endpoint exists so the frontend can switch to the SWA API
    # path immediately, and the backend can be wired up in Slice 3.
    return _json_response(
        {
            "submission_id": submission_id,
            "status": "pending",
            "message": "Status polling endpoint active — pipeline status will be wired in Slice 3",
        }
    )


# ---------------------------------------------------------------------------
# GET /api/analysis/history — recent signed-in analysis runs
# ---------------------------------------------------------------------------

_DEFAULT_HISTORY_LIMIT = 8
_MAX_HISTORY_LIMIT = 20
_MAX_HISTORY_OFFSET = 200
_DEFAULT_PROVIDER = "planetary-computer"

_ACTIVE_STATUSES = frozenset({"submitted", "pending", "running", "continuedasnew"})


def _parse_int_param(raw: str, default: int, lo: int, hi: int) -> int:
    """Parse and clamp an integer query parameter."""
    try:
        return max(lo, min(int(raw), hi))
    except (TypeError, ValueError):
        return default


def _history_entry(record: dict) -> dict:
    """Transform a Cosmos runs record into the frontend history entry shape."""
    instance_id = str(record.get("instance_id") or record.get("submission_id") or "")
    runtime_status = record.get("status", "submitted")

    return {
        "submissionId": record.get("submission_id", instance_id),
        "instanceId": instance_id,
        "submittedAt": record.get("submitted_at", ""),
        "submissionPrefix": record.get("submission_prefix", "analysis"),
        "providerName": record.get("provider_name", _DEFAULT_PROVIDER),
        "featureCount": record.get("feature_count"),
        "aoiCount": record.get("aoi_count"),
        "processingMode": record.get("processing_mode"),
        "maxSpreadKm": record.get("max_spread_km"),
        "totalAreaHa": record.get("total_area_ha"),
        "largestAreaHa": record.get("largest_area_ha"),
        "workspaceRole": record.get("workspace_role"),
        "workspacePreference": record.get("workspace_preference"),
        "runtimeStatus": runtime_status,
        "createdTime": record.get("submitted_at", ""),
        "lastUpdatedTime": record.get("submitted_at", ""),
        "customStatus": None,
        "output": None,
        "artifactCount": 0,
        "partialFailures": {"imagery": 0, "downloads": 0, "postProcess": 0},
        "kmlBlobName": record.get("kml_blob_name", ""),
        "kmlSizeBytes": record.get("kml_size_bytes", 0),
    }


@app.function_name("analysis_history")
@app.route(
    route="analysis/history",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def analysis_history(req: func.HttpRequest) -> func.HttpResponse:
    """Lightweight analysis history — reads runs from Cosmos without DF status.

    The Container Apps version enriches each run with live Durable Functions
    status.  This SWA version returns Cosmos-only data (status field from the
    record).  For in-flight runs the status may lag, but the active polling
    endpoint (upload/status) covers that path.
    """
    # --- auth (SWA built-in — x-ms-client-principal) ---
    try:
        claims = _parse_client_principal(req)
    except ValueError as exc:
        logger.warning("History auth failed: %s", exc)
        return _error(401, "Unauthorized")

    user_id: str = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    params = getattr(req, "params", {}) or {}
    limit = _parse_int_param(params.get("limit", ""), _DEFAULT_HISTORY_LIMIT, 1, _MAX_HISTORY_LIMIT)
    offset = _parse_int_param(params.get("offset", ""), 0, 0, _MAX_HISTORY_OFFSET)

    try:
        container = _get_cosmos_container("runs")
        query = (
            "SELECT c.submission_id, c.instance_id, c.submitted_at,"
            " c.status, c.submission_prefix, c.provider_name,"
            " c.feature_count, c.aoi_count, c.processing_mode,"
            " c.max_spread_km, c.total_area_ha, c.largest_area_ha,"
            " c.workspace_role, c.workspace_preference,"
            " c.kml_blob_name, c.kml_size_bytes"
            " FROM c WHERE c.user_id = @uid"
            " ORDER BY c.submitted_at DESC OFFSET @off LIMIT @lim"
        )
        records = list(
            container.query_items(
                query=query,
                parameters=[
                    {"name": "@uid", "value": user_id},
                    {"name": "@off", "value": offset},
                    {"name": "@lim", "value": limit},
                ],
                partition_key=user_id,
            )
        )
    except RuntimeError:
        return _error(503, "Analysis history temporarily unavailable")
    except Exception:
        logger.exception("Cosmos query failed for analysis history")
        return _error(503, "Analysis history temporarily unavailable")

    runs = [_history_entry(r) for r in records]
    active_run = next(
        (r for r in runs if r["runtimeStatus"].strip().lower() in _ACTIVE_STATUSES),
        None,
    )

    return _json_response(
        {
            "runs": runs,
            "activeRun": active_run,
            "offset": offset,
            "limit": limit,
        }
    )

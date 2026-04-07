"""SWA managed API functions — lightweight, always-warm endpoints.

These functions run inside the Static Web App's managed function runtime.
They handle user-interactive requests (SAS token minting, status polling)
so the main Container Apps function app can scale to zero without affecting UX.

Environment variables (set via SWA app_settings in OpenTofu):
  STORAGE_ACCOUNT_NAME   — storage account for SAS token generation
  STORAGE_ACCOUNT_KEY    — storage account key (for SAS signing)
  CIAM_TENANT_NAME       — e.g. "treesightauth"
  CIAM_CLIENT_ID         — CIAM app registration client ID
  SAS_TOKEN_EXPIRY_MINUTES — SAS token lifetime (default: 15)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid

import azure.functions as func
import jwt
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    generate_blob_sas,
)

app = func.FunctionApp()
logger = logging.getLogger("swa-api")

# ---------------------------------------------------------------------------
# Configuration (read once at cold-start)
# ---------------------------------------------------------------------------

STORAGE_ACCOUNT_NAME = os.environ.get("STORAGE_ACCOUNT_NAME", "")
STORAGE_ACCOUNT_KEY = os.environ.get("STORAGE_ACCOUNT_KEY", "")
CIAM_TENANT_NAME = os.environ.get("CIAM_TENANT_NAME", "")
CIAM_CLIENT_ID = os.environ.get("CIAM_CLIENT_ID", "")
INPUT_CONTAINER = os.environ.get("INPUT_CONTAINER", "kml-input")
SAS_TOKEN_EXPIRY_MINUTES = int(os.environ.get("SAS_TOKEN_EXPIRY_MINUTES", "15"))
MAX_UPLOAD_BYTES = 10_485_760  # 10 MiB — matches treesight MAX_KML_FILE_SIZE_BYTES

# JWKS URI for CIAM token validation
_JWKS_URI = (
    f"https://{CIAM_TENANT_NAME}.ciamlogin.com/"
    f"{CIAM_TENANT_NAME}.onmicrosoft.com/discovery/v2.0/keys"
    if CIAM_TENANT_NAME
    else ""
)
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    """Lazy-init JWKS client (caches keys across invocations)."""
    global _jwks_client
    if _jwks_client is None:
        if not _JWKS_URI:
            raise RuntimeError("CIAM_TENANT_NAME is not configured")
        _jwks_client = jwt.PyJWKClient(_JWKS_URI)
    return _jwks_client


def _validate_token(auth_header: str) -> dict:
    """Validate a CIAM JWT and return its claims.

    Raises ``ValueError`` on any validation failure.
    """
    if not auth_header.startswith("Bearer "):
        raise ValueError("Missing Bearer token")

    token = auth_header[7:]
    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=CIAM_CLIENT_ID,
        options={"require": ["sub", "exp", "aud"]},
    )
    return claims


def _error(status: int, message: str) -> func.HttpResponse:
    """Return a JSON error response."""
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=status,
        mimetype="application/json",
    )


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
    # --- auth ---
    auth_header = req.headers.get("Authorization", "")
    try:
        claims = _validate_token(auth_header)
    except (ValueError, jwt.PyJWTError, RuntimeError) as exc:
        logger.warning("Token validation failed: %s", exc)
        return _error(401, "Unauthorized")

    user_id = claims.get("sub", "")
    if not user_id:
        return _error(401, "Token missing subject claim")

    # --- config check ---
    if not STORAGE_ACCOUNT_NAME or not STORAGE_ACCOUNT_KEY:
        logger.error("Storage account not configured for SAS generation")
        return _error(503, "Service not configured")

    # --- mint SAS ---
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
        ticket["submission_context"] = ctx

    try:
        account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
        blob_service = BlobServiceClient(account_url=account_url, credential=STORAGE_ACCOUNT_KEY)
        ticket_blob = blob_service.get_blob_client(
            INPUT_CONTAINER, f".tickets/{submission_id}.json"
        )
        ticket_blob.upload_blob(
            json.dumps(ticket).encode(),
            overwrite=True,
            content_type="application/json",
        )
    except Exception:
        logger.exception("Failed to write ticket for submission_id=%s", submission_id)
        return _error(502, "Storage service temporarily unavailable")

    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=INPUT_CONTAINER,
        blob_name=blob_name,
        account_key=STORAGE_ACCOUNT_KEY,
        permission=BlobSasPermissions(create=True, write=True),
        expiry=datetime.datetime.now(datetime.UTC)
        + datetime.timedelta(minutes=SAS_TOKEN_EXPIRY_MINUTES),
        content_type="application/vnd.google-earth.kml+xml",
    )

    sas_url = (
        f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net/"
        f"{INPUT_CONTAINER}/{blob_name}?{sas_token}"
    )

    logger.info(
        "SAS token minted user_id=%s submission_id=%s blob=%s",
        user_id,
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
    auth_header = req.headers.get("Authorization", "")
    try:
        _validate_token(auth_header)
    except (ValueError, jwt.PyJWTError, RuntimeError) as exc:
        logger.warning("Token validation failed: %s", exc)
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

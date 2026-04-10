"""SWA managed API functions — lightweight, always-warm endpoints.

These functions run inside the Static Web App's managed function runtime.
They handle user-interactive requests (SAS token minting, status polling,
billing status/checkout/portal, contact form, readiness, catalogue) so the
main Container Apps function app can scale to zero without affecting UX.

Authentication is handled by the SWA platform using built-in custom auth
(Azure AD / Entra External ID).  SWA injects user identity via the
``x-ms-client-principal`` header — a Base64-encoded JSON payload containing
``identityProvider``, ``userId``, ``userDetails``, and ``userRoles``.

Environment variables (set via SWA app_settings in OpenTofu):
  STORAGE_ACCOUNT_NAME   — storage account for SAS token generation
  SAS_TOKEN_EXPIRY_MINUTES — SAS token lifetime (default: 15)
  STRIPE_API_KEY         — Stripe secret key (Key Vault reference)
  STRIPE_PRICE_ID_PRO_*  — Stripe Price IDs per currency
  BILLING_ALLOWED_USERS  — comma-separated user IDs allowed to use billing
  COMMUNICATION_SERVICES_CONNECTION_STRING — ACS connection string (email)
  EMAIL_SENDER_ADDRESS   — sender address for email notifications
  NOTIFICATION_EMAIL     — recipient for contact-form notifications

Authentication to Azure Storage uses the SWA's user-assigned managed
identity (DefaultAzureCredential + AZURE_CLIENT_ID) — no shared secrets.
"""

from __future__ import annotations

import base64
import datetime
import html
import json
import logging
import os
import re
import threading
import time
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

# Stripe billing
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_PRICE_ID_PRO_GBP = os.environ.get("STRIPE_PRICE_ID_PRO_GBP", "")
STRIPE_PRICE_ID_PRO_USD = os.environ.get("STRIPE_PRICE_ID_PRO_USD", "")
STRIPE_PRICE_ID_PRO_EUR = os.environ.get("STRIPE_PRICE_ID_PRO_EUR", "")
SUPPORTED_CURRENCIES = ("GBP", "USD", "EUR")
DEFAULT_CURRENCY = "GBP"

# Feature gate — restrict billing to named users while Stripe is in test mode
BILLING_ALLOWED_USERS: frozenset[str] = frozenset(
    uid.strip() for uid in os.environ.get("BILLING_ALLOWED_USERS", "").split(",") if uid.strip()
)

# Plan tier configuration — mirrors treesight.security.billing.PLAN_CATALOG
# Intentionally duplicated: SWA functions must not import treesight.
PLAN_CATALOG: dict[str, dict] = {
    "demo": {
        "label": "Demo",
        "run_limit": 3,
        "aoi_limit": 1,
        "concurrency": 1,
        "ai_insights": False,
        "api_access": False,
        "export": False,
        "retention_days": 0,
        "temporal_cadence": "seasonal",
        "max_history_years": 2,
        "overage_rate": None,
    },
    "free": {
        "label": "Free",
        "run_limit": 5,
        "aoi_limit": 5,
        "concurrency": 1,
        "ai_insights": False,
        "api_access": False,
        "export": False,
        "retention_days": 30,
        "temporal_cadence": "seasonal",
        "max_history_years": 2,
        "overage_rate": None,
    },
    "starter": {
        "label": "Starter",
        "run_limit": 15,
        "aoi_limit": 15,
        "concurrency": 2,
        "ai_insights": True,
        "api_access": False,
        "export": True,
        "retention_days": 60,
        "temporal_cadence": "seasonal",
        "max_history_years": None,
        "overage_rate": 1.50,
    },
    "pro": {
        "label": "Pro",
        "run_limit": 50,
        "aoi_limit": 50,
        "concurrency": 5,
        "ai_insights": True,
        "api_access": False,
        "export": True,
        "retention_days": 90,
        "temporal_cadence": "monthly",
        "max_history_years": None,
        "overage_rate": 0.80,
    },
    "team": {
        "label": "Team",
        "run_limit": 200,
        "aoi_limit": 200,
        "concurrency": 10,
        "ai_insights": True,
        "api_access": True,
        "export": True,
        "retention_days": 365,
        "temporal_cadence": "monthly",
        "max_history_years": None,
        "overage_rate": 0.50,
    },
    "enterprise": {
        "label": "Enterprise",
        "run_limit": 10_000,
        "aoi_limit": None,
        "concurrency": 25,
        "ai_insights": True,
        "api_access": True,
        "export": True,
        "retention_days": None,
        "temporal_cadence": "maximum",
        "max_history_years": None,
        "overage_rate": None,
    },
}

GATED_PRICE_LABELS: dict[str, str] = {
    "demo": "Free",
    "free": "Free",
    "starter": "$",
    "pro": "$$",
    "team": "$$$",
    "enterprise": "Price on Enquiry",
}

# Contact form — Azure Communication Services email
COMMUNICATION_SERVICES_CONNECTION_STRING = os.environ.get(
    "COMMUNICATION_SERVICES_CONNECTION_STRING", ""
)
EMAIL_SENDER_ADDRESS = os.environ.get("EMAIL_SENDER_ADDRESS", "")
NOTIFICATION_EMAIL = os.environ.get("NOTIFICATION_EMAIL", "")
CONTACT_SUBMISSIONS_CONTAINER = "pipeline-payloads"

# Email validation — same pattern as blueprints/_helpers.py
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_FIELD_LEN = 2000

# API contract version — mirrors treesight.constants.API_CONTRACT_VERSION.
# Intentionally duplicated: SWA functions must not import treesight.
API_CONTRACT_VERSION = "2026-03-15.1"

# Rate limiter — 5 requests per 60s per IP (mirrors treesight form_limiter)
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = 60
_rate_hits: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def _rate_limit_allowed(key: str) -> bool:
    """Sliding-window rate limiter for contact form."""
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW
    with _rate_lock:
        timestamps = _rate_hits.get(key, [])
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= _RATE_LIMIT_MAX:
            _rate_hits[key] = timestamps
            return False
        timestamps.append(now)
        _rate_hits[key] = timestamps
        # Evict stale keys to prevent unbounded memory growth
        stale = [k for k, ts in _rate_hits.items() if not ts or ts[-1] <= cutoff]
        for k in stale:
            del _rate_hits[k]
        return True


def _get_client_ip(req: func.HttpRequest) -> str:
    """Extract client IP from Azure request headers.

    Prefers ``X-Azure-ClientIP`` (set by SWA / Container Apps).
    Falls back to the rightmost ``X-Forwarded-For`` entry — Azure
    platforms append the real client IP as the last entry, unlike the
    standard convention where it is first.  This resists spoofing by
    ignoring client-supplied entries earlier in the chain.
    """
    azure_ip = req.headers.get("X-Azure-ClientIP", "")
    if azure_ip:
        return azure_ip.strip()
    forwarded = req.headers.get("X-Forwarded-For", "")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return "unknown"


_blob_service: BlobServiceClient | None = None
_cosmos_db: object | None = None  # Azure Cosmos DatabaseProxy

# Production domain used as fallback for redirect URLs.
_DEFAULT_ORIGIN = "https://canopex.hrdcrprwn.com"

_ALLOWED_ORIGINS: set[str] = {
    "https://polite-glacier-0d6885003.4.azurestaticapps.net",
    "https://canopex.hrdcrprwn.com",
    "http://localhost:4280",
    "http://localhost:1111",
}

_extra_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _extra_origins:
    for _o in _extra_origins.split(","):
        _o = _o.strip()
        if _o and _o.startswith("https://"):
            _ALLOWED_ORIGINS.add(_o)


def _safe_origin(req: func.HttpRequest) -> str:
    """Return request Origin if allow-listed, else the default production URL."""
    origin = req.headers.get("Origin", "")
    return origin if origin in _ALLOWED_ORIGINS else _DEFAULT_ORIGIN


# ---------------------------------------------------------------------------
# GET /api/health — anonymous lightweight liveness probe
# ---------------------------------------------------------------------------


@app.function_name("health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Lightweight liveness probe — always returns 200.

    Used by the frontend ``discoverApiBase()`` to determine whether the
    SWA managed API is reachable.  Intentionally anonymous (no auth).
    """
    return func.HttpResponse(
        json.dumps({"status": "ok"}),
        status_code=200,
        mimetype="application/json",
    )


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

    if not isinstance(principal, dict):
        raise ValueError("Client principal is not a JSON object")

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

    Requires a valid SWA session (X-MS-CLIENT-PRINCIPAL header).
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


# ---------------------------------------------------------------------------
# Billing helpers
# ---------------------------------------------------------------------------

_LOCAL_EMULATION_ORIGINS = frozenset(
    {
        "http://localhost:4280",
        "http://127.0.0.1:4280",
        "http://localhost:1111",
        "http://127.0.0.1:1111",
    }
)


def _stripe_configured() -> bool:
    return bool(
        STRIPE_API_KEY
        and (STRIPE_PRICE_ID_PRO_EUR or STRIPE_PRICE_ID_PRO_GBP or STRIPE_PRICE_ID_PRO_USD)
    )


def _get_stripe():
    """Lazily import and configure Stripe SDK."""
    import stripe

    stripe.api_key = STRIPE_API_KEY
    return stripe


def _normalize_tier(tier: str | None) -> str:
    candidate = (tier or "free").strip().lower()
    return candidate if candidate in PLAN_CATALOG else "free"


def _plan_capabilities(tier: str | None) -> dict:
    normalized = _normalize_tier(tier)
    plan = dict(PLAN_CATALOG[normalized])
    plan["tier"] = normalized
    return plan


def _billing_allowed(user_id: str | None) -> bool:
    if not user_id or user_id == "anonymous":
        return False
    if not BILLING_ALLOWED_USERS:
        return False
    return user_id in BILLING_ALLOWED_USERS


def _tier_emulation_allowed(req) -> bool:
    origin = req.headers.get("Origin", "")
    return origin in _LOCAL_EMULATION_ORIGINS


def _get_subscription(user_id: str) -> dict:
    """Read subscription record from Cosmos, defaulting to free tier."""
    try:
        container = _get_cosmos_container("subscriptions")
        doc = container.read_item(item=user_id, partition_key=user_id)
        return {k: v for k, v in doc.items() if not k.startswith("_")}
    except Exception:
        return {"tier": "free", "status": "none"}


def _get_subscription_emulation(user_id: str) -> dict | None:
    """Read emulation record from Cosmos, returning None if not active."""
    try:
        container = _get_cosmos_container("subscriptions")
        doc = container.read_item(item=f"{user_id}:emulation", partition_key=user_id)
        if not doc or not doc.get("enabled"):
            return None
        return {
            "tier": _normalize_tier(doc.get("tier")),
            "status": "active",
            "enabled": True,
            "updated_at": doc.get("updated_at"),
        }
    except Exception:
        return None


def _get_effective_subscription(user_id: str) -> dict:
    """Return billing record overlaid with any active emulation."""
    subscription = dict(_get_subscription(user_id))
    emulation = _get_subscription_emulation(user_id)
    if not emulation:
        subscription["emulated"] = False
        return subscription
    effective = dict(subscription)
    effective.update(
        {
            "tier": emulation["tier"],
            "status": emulation["status"],
            "emulated": True,
            "billing_tier": _normalize_tier(subscription.get("tier")),
            "billing_status": subscription.get("status", "none"),
            "emulation_updated_at": emulation.get("updated_at"),
        }
    )
    return effective


def _get_usage(user_id: str) -> dict:
    """Return pipeline run usage: {used, limit}."""
    effective = _get_effective_subscription(user_id)
    tier = _normalize_tier(effective.get("tier"))
    if effective.get("status") == "active" or tier == "free":
        run_limit = _plan_capabilities(tier)["run_limit"]
    else:
        run_limit = _plan_capabilities("free")["run_limit"]
    try:
        container = _get_cosmos_container("users")
        doc = container.read_item(item=user_id, partition_key=user_id)
        quota = doc.get("quota", {"used": 0})
        used = quota.get("used", 0)
    except Exception:
        used = 0
    return {"used": used, "limit": run_limit}


def _billing_status_payload(user_id: str, req) -> dict:
    """Assemble the full billing status response."""
    subscription = _get_subscription(user_id)
    effective = _get_effective_subscription(user_id)
    emulation = _get_subscription_emulation(user_id)
    capabilities = _plan_capabilities(effective.get("tier"))

    gated = not _billing_allowed(user_id)
    usage = _get_usage(user_id)

    payload = {
        "tier": effective.get("tier", "free"),
        "status": effective.get("status", "none"),
        "runs_remaining": max(usage["limit"] - usage["used"], 0),
        "runs_used": usage["used"],
        "billing_configured": _stripe_configured(),
        "billing_gated": gated,
        "tier_source": "emulated" if effective.get("emulated") else "billing",
        "capabilities": capabilities,
        "subscription": {
            "tier": subscription.get("tier", "free"),
            "status": subscription.get("status", "none"),
        },
        "emulation": {
            "available": _tier_emulation_allowed(req),
            "active": bool(emulation),
            "tier": emulation.get("tier") if emulation else None,
            "tiers": list(PLAN_CATALOG.keys()),
        },
    }
    if gated:
        payload["price_labels"] = GATED_PRICE_LABELS
    return payload


# ---------------------------------------------------------------------------
# GET /api/billing/status — current user's subscription + quota status
# ---------------------------------------------------------------------------


@app.function_name("billing_status")
@app.route(route="billing/status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def billing_status(req: func.HttpRequest) -> func.HttpResponse:
    """Return the user's billing tier, quota usage, and capabilities."""
    try:
        claims = _parse_client_principal(req)
    except ValueError:
        return _error(401, "Unauthorized")

    user_id = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    try:
        payload = _billing_status_payload(user_id, req)
    except Exception:
        logger.exception("Failed to build billing status for user=%s", user_id)
        return _error(503, "Billing status temporarily unavailable")

    return _json_response(payload)


# ---------------------------------------------------------------------------
# POST /api/billing/checkout — create a Stripe Checkout session
# ---------------------------------------------------------------------------


@app.function_name("billing_checkout")
@app.route(route="billing/checkout", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def billing_checkout(req: func.HttpRequest) -> func.HttpResponse:
    """Create a Stripe Checkout session for Pro subscription."""
    try:
        claims = _parse_client_principal(req)
    except ValueError:
        return _error(401, "Unauthorized")

    user_id = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    if not _billing_allowed(user_id):
        return _error(
            403,
            "Billing is not yet available for your account. "
            "Use the contact form to express interest and we'll be in touch.",
        )

    if not _stripe_configured():
        return _error(503, "Billing not configured")

    # Determine currency — malformed body is not an error, just use default.
    currency = ""
    try:
        body = json.loads(req.get_body()) if req.get_body() else {}
        currency = body.get("currency", "").upper()
    except (ValueError, UnicodeDecodeError):
        pass  # Malformed JSON body — fall through to default currency
    if currency not in SUPPORTED_CURRENCIES:
        currency = DEFAULT_CURRENCY

    if currency == "USD":
        price_id = STRIPE_PRICE_ID_PRO_USD
    elif currency == "EUR":
        price_id = STRIPE_PRICE_ID_PRO_EUR
    else:
        price_id = STRIPE_PRICE_ID_PRO_GBP

    if not price_id:
        return _error(503, f"Billing not configured for {currency}")

    stripe = _get_stripe()
    origin = _safe_origin(req)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{origin}?billing=success",
            cancel_url=f"{origin}?billing=cancel",
            client_reference_id=user_id,
            metadata={"user_id": user_id, "currency": currency},
            billing_address_collection="required",
            automatic_tax={"enabled": True},
            consent_collection={"terms_of_service": "required"},
            custom_text={
                "terms_of_service_acceptance": {
                    "message": (
                        "I agree to the [Terms of Service]"
                        "(https://canopex.hrdcrprwn.com/terms.html)"
                        " and acknowledge my right to cancel within"
                        " 14 days under the Consumer Contracts"
                        " Regulations 2013."
                    )
                }
            },
            allow_promotion_codes=True,
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe checkout session creation failed")
        msg = getattr(exc, "user_message", None) or "Payment provider error"
        return _error(502, msg)

    logger.info("Checkout session created user=%s currency=%s", user_id, currency)
    return _json_response({"checkout_url": session.url})


# ---------------------------------------------------------------------------
# POST /api/billing/portal — create a Stripe Customer Portal session
# ---------------------------------------------------------------------------


@app.function_name("billing_portal")
@app.route(route="billing/portal", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def billing_portal(req: func.HttpRequest) -> func.HttpResponse:
    """Create a Stripe Customer Portal session for self-service billing."""
    try:
        claims = _parse_client_principal(req)
    except ValueError:
        return _error(401, "Unauthorized")

    user_id = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    if not _billing_allowed(user_id):
        return _error(403, "Billing is not available for your account")

    if not _stripe_configured():
        return _error(503, "Billing not configured")

    sub = _get_subscription(user_id)
    customer_id = sub.get("stripe_customer_id")
    if not customer_id:
        return _error(404, "No active subscription found")

    stripe = _get_stripe()
    origin = _safe_origin(req)

    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{origin}?billing=portal-return",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe portal session creation failed")
        msg = getattr(exc, "user_message", None) or "Payment provider error"
        return _error(502, msg)

    logger.info("Portal session created user=%s", user_id)
    return _json_response({"portal_url": session.url})


# ---------------------------------------------------------------------------
# POST /api/contact-form — anonymous early-access / contact submission
# ---------------------------------------------------------------------------


def _sanitise(value: str) -> str:
    """Strip and truncate a user-supplied string field."""
    return value.strip()[:_MAX_FIELD_LEN] if isinstance(value, str) else ""


def _send_contact_notification(record: dict) -> bool:
    """Forward a contact-form submission to the notification address via ACS.

    Returns True on success, False on failure.  Never raises.
    """
    if not NOTIFICATION_EMAIL:
        logger.info("NOTIFICATION_EMAIL not set — skipping contact notification")
        return False
    if not COMMUNICATION_SERVICES_CONNECTION_STRING or not EMAIL_SENDER_ADDRESS:
        logger.warning("Email not configured — skipping contact notification")
        return False

    # Escape user-supplied values before embedding in HTML
    email_val = html.escape(record.get("email", "unknown"))
    org = html.escape(record.get("organization", "\u2014"))
    use_case = html.escape(record.get("use_case", "\u2014"))
    submitted = html.escape(record.get("submitted_at", "\u2014"))
    submission_id = html.escape(record.get("submission_id", "\u2014"))

    raw_subject = f"Canopex contact: {record.get('organization') or record.get('email', 'unknown')}"
    subject = raw_subject.replace("\r", "").replace("\n", " ")[:200]
    body_html = (
        "<h2>New Contact Form Submission</h2>"
        "<table>"
        f"<tr><td><strong>Email:</strong></td><td>{email_val}</td></tr>"
        f"<tr><td><strong>Organisation:</strong></td><td>{org}</td></tr>"
        f"<tr><td><strong>Use Case:</strong></td><td>{use_case}</td></tr>"
        f"<tr><td><strong>Submitted:</strong></td><td>{submitted}</td></tr>"
        f"<tr><td><strong>ID:</strong></td><td>{submission_id}</td></tr>"
        "</table>"
    )
    dash = "\u2014"
    body_text = (
        "New Contact Form Submission\n\n"
        f"Email: {record.get('email', 'unknown')}\n"
        f"Organisation: {record.get('organization', dash)}\n"
        f"Use Case: {record.get('use_case', dash)}\n"
        f"Submitted: {record.get('submitted_at', dash)}\n"
        f"ID: {record.get('submission_id', dash)}\n"
    )

    try:
        from azure.communication.email import EmailClient

        client = EmailClient.from_connection_string(COMMUNICATION_SERVICES_CONNECTION_STRING)
        message = {
            "senderAddress": EMAIL_SENDER_ADDRESS,
            "recipients": {"to": [{"address": NOTIFICATION_EMAIL}]},
            "content": {
                "subject": subject,
                "html": body_html,
                "plainText": body_text,
            },
        }
        poller = client.begin_send(message)
        result = poller.result()
        logger.info("Contact notification sent: id=%s", result.get("id"))
        return True
    except Exception:
        logger.exception("Failed to send contact notification")
        return False


@app.function_name("contact_form")
@app.route(route="contact-form", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def contact_form(req: func.HttpRequest) -> func.HttpResponse:
    """Accept a contact-form submission: validate, store, notify."""
    # Rate limit by client IP
    client_ip = _get_client_ip(req)
    if not _rate_limit_allowed(client_ip):
        return _error(429, "Rate limit exceeded \u2014 try again later")

    try:
        body = req.get_json()
    except ValueError:
        return _error(400, "Invalid JSON body")

    if not isinstance(body, dict):
        return _error(400, "Expected JSON object")

    email = _sanitise(body.get("email", ""))
    if not email or not _EMAIL_RE.match(email):
        return _error(400, "Valid email is required")

    # Accept both British and American spelling
    organization = _sanitise(body.get("organisation", "") or body.get("organization", ""))
    use_case = _sanitise(body.get("use_case", ""))

    submission_id = str(uuid.uuid4())
    record = {
        "submission_id": submission_id,
        "email": email,
        "organization": organization,
        "use_case": use_case,
        "submitted_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "source": "marketing_website",
        "ip_forwarded_for": _sanitise(req.headers.get("X-Forwarded-For", "")),
    }

    # Store submission in blob storage
    try:
        blob_service = _get_blob_service()
        blob_client = blob_service.get_blob_client(
            CONTACT_SUBMISSIONS_CONTAINER,
            f"contact-submissions/{submission_id}.json",
        )
        blob_client.upload_blob(
            json.dumps(record).encode(),
            overwrite=False,
            content_settings=ContentSettings(content_type="application/json"),
        )
    except Exception:
        logger.exception("Failed to store contact submission %s", submission_id)
        return _error(502, "Submission storage temporarily unavailable")

    # Best-effort email notification (failure doesn't affect user response)
    _send_contact_notification(record)

    logger.info("Contact form submitted submission_id=%s", submission_id)
    return _json_response({"status": "received", "submission_id": submission_id})


# ---------------------------------------------------------------------------
# GET /api/readiness — anonymous service readiness probe
# ---------------------------------------------------------------------------


@app.function_name("readiness")
@app.route(route="readiness", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def readiness(req: func.HttpRequest) -> func.HttpResponse:
    """Readiness probe — returns API version, version, and commit SHA."""
    return _json_response(
        {
            "status": "ready",
            "api_version": API_CONTRACT_VERSION,
            "version": os.environ.get("BUILD_VERSION", "swa-managed"),
            "commit": os.environ.get("BUILD_SHA", "unknown"),
        }
    )


# ---------------------------------------------------------------------------
# GET /api/contract — API contract version
# ---------------------------------------------------------------------------


@app.function_name("contract")
@app.route(route="contract", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def contract(req: func.HttpRequest) -> func.HttpResponse:
    """Return the current API contract version."""
    return _json_response({"api_version": API_CONTRACT_VERSION})


# ---------------------------------------------------------------------------
# Catalogue constants (mirrored from treesight — SWA cannot import it)
# ---------------------------------------------------------------------------

_CATALOGUE_CONTAINER = "catalogue"
_CATALOGUE_MAX_LIMIT = 100
_CATALOGUE_MAX_OFFSET = 10_000

# ---------------------------------------------------------------------------
# Catalogue helpers
# ---------------------------------------------------------------------------

# Map from Cosmos snake_case field names to camelCase API keys.
_CATALOGUE_CAMEL_MAP: list[tuple[str, str]] = [
    ("id", "id"),
    ("run_id", "runId"),
    ("aoi_name", "aoiName"),
    ("source_file", "sourceFile"),
    ("provider", "provider"),
    ("centroid", "centroid"),
    ("bbox", "bbox"),
    ("area_ha", "areaHa"),
    ("acquired_at", "acquiredAt"),
    ("submitted_at", "submittedAt"),
    ("cloud_cover_pct", "cloudCoverPct"),
    ("spatial_resolution_m", "spatialResolutionM"),
    ("collection", "collection"),
    ("status", "status"),
    ("ndvi_mean", "ndviMean"),
    ("ndvi_min", "ndviMin"),
    ("ndvi_max", "ndviMax"),
    ("change_loss_pct", "changeLossPct"),
    ("change_gain_pct", "changeGainPct"),
    ("change_mean_delta", "changeMeanDelta"),
    ("imagery_blob_path", "imageryBlobPath"),
    ("metadata_blob_path", "metadataBlobPath"),
    ("enrichment_manifest_path", "enrichmentManifestPath"),
    ("created_at", "createdAt"),
    ("updated_at", "updatedAt"),
]


def _catalogue_entry(doc: dict) -> dict:
    """Transform a Cosmos catalogue document to a camelCase API entry."""
    return {camel: doc.get(snake) for snake, camel in _CATALOGUE_CAMEL_MAP}


def _catalogue_list_body(
    entries: list[dict],
    total: int,
    offset: int,
    limit: int,
) -> dict:
    """Build the paginated catalogue list response."""
    return {
        "entries": [_catalogue_entry(doc) for doc in entries],
        "total": total,
        "offset": offset,
        "limit": limit,
        "hasMore": offset + limit < total,
    }


def _parse_iso(value: str | None) -> str | None:
    """Validate an ISO-8601 date string, returning None on failure."""
    if not value:
        return None
    try:
        datetime.datetime.fromisoformat(value)
        return value
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# GET /api/catalogue — paginated list with filters
# ---------------------------------------------------------------------------


@app.function_name("catalogue_list")
@app.route(
    route="catalogue",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def catalogue_list(req: func.HttpRequest) -> func.HttpResponse:
    """List catalogue entries with optional filters and pagination."""
    try:
        claims = _parse_client_principal(req)
    except ValueError:
        return _error(401, "Unauthorized")
    user_id: str = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    params = req.params or {}
    limit = _parse_int_param(params.get("limit", ""), 20, 1, _CATALOGUE_MAX_LIMIT)
    offset = _parse_int_param(params.get("offset", ""), 0, 0, _CATALOGUE_MAX_OFFSET)
    sort = params.get("sort", "desc")
    if sort not in ("asc", "desc"):
        sort = "desc"

    # Build dynamic Cosmos SQL filters (parameterised)
    conditions: list[str] = []
    query_params: list[dict] = []

    aoi_name = params.get("aoiName")
    if aoi_name:
        conditions.append("CONTAINS(LOWER(c.aoi_name), @aoi_name)")
        query_params.append({"name": "@aoi_name", "value": aoi_name.lower()})

    status_filter = params.get("status")
    if status_filter:
        conditions.append("c.status = @status")
        query_params.append({"name": "@status", "value": status_filter})

    date_from = _parse_iso(params.get("dateFrom"))
    if date_from:
        conditions.append("c.submitted_at >= @date_from")
        query_params.append({"name": "@date_from", "value": date_from})

    date_to = _parse_iso(params.get("dateTo"))
    if date_to:
        conditions.append("c.submitted_at <= @date_to")
        query_params.append({"name": "@date_to", "value": date_to})

    provider = params.get("provider")
    if provider:
        conditions.append("c.provider = @provider")
        query_params.append({"name": "@provider", "value": provider})

    where = " AND ".join(conditions) if conditions else "true"
    order = "DESC" if sort == "desc" else "ASC"

    try:
        container = _get_cosmos_container(_CATALOGUE_CONTAINER)

        count_result = list(
            container.query_items(
                query=f"SELECT VALUE COUNT(1) FROM c WHERE {where}",  # noqa: S608
                parameters=query_params,
                partition_key=user_id,
            )
        )
        total: int = int(count_result[0]) if count_result else 0

        data_params = [
            *query_params,
            {"name": "@off", "value": offset},
            {"name": "@lim", "value": limit},
        ]
        docs = list(
            container.query_items(
                query=(
                    f"SELECT * FROM c WHERE {where}"  # noqa: S608
                    f" ORDER BY c.submitted_at {order}"
                    f" OFFSET @off LIMIT @lim"
                ),
                parameters=data_params,
                partition_key=user_id,
            )
        )
    except RuntimeError:
        return _error(503, "Catalogue temporarily unavailable")
    except Exception:
        logger.exception("Cosmos query failed for catalogue list")
        return _error(503, "Catalogue temporarily unavailable")

    return _json_response(_catalogue_list_body(docs, total, offset, limit))


# ---------------------------------------------------------------------------
# GET /api/catalogue/{entryId} — single entry
# ---------------------------------------------------------------------------


@app.function_name("catalogue_detail")
@app.route(
    route="catalogue/{entryId}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def catalogue_detail(req: func.HttpRequest) -> func.HttpResponse:
    """Get a single catalogue entry by id."""
    try:
        claims = _parse_client_principal(req)
    except ValueError:
        return _error(401, "Unauthorized")
    user_id: str = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    entry_id = req.route_params.get("entryId", "")
    if not entry_id:
        return _error(400, "Missing entryId")

    try:
        container = _get_cosmos_container(_CATALOGUE_CONTAINER)
        doc = container.read_item(item=entry_id, partition_key=user_id)
    except RuntimeError:
        return _error(503, "Catalogue temporarily unavailable")
    except Exception as exc:
        # CosmosResourceNotFoundError has status_code 404
        if getattr(exc, "status_code", None) == 404:
            return _error(404, "Catalogue entry not found")
        logger.exception("Cosmos read failed for catalogue detail")
        return _error(503, "Catalogue temporarily unavailable")

    return _json_response(_catalogue_entry(doc))


# ---------------------------------------------------------------------------
# GET /api/catalogue/run/{runId} — entries for a pipeline run
# ---------------------------------------------------------------------------


@app.function_name("catalogue_by_run")
@app.route(
    route="catalogue/run/{runId}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def catalogue_by_run(req: func.HttpRequest) -> func.HttpResponse:
    """List all catalogue entries for a specific pipeline run."""
    try:
        claims = _parse_client_principal(req)
    except ValueError:
        return _error(401, "Unauthorized")
    user_id: str = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    run_id = req.route_params.get("runId", "")
    if not run_id:
        return _error(400, "Missing runId")

    try:
        container = _get_cosmos_container(_CATALOGUE_CONTAINER)
        docs = list(
            container.query_items(
                query=("SELECT * FROM c WHERE c.run_id = @rid ORDER BY c.aoi_name ASC"),
                parameters=[{"name": "@rid", "value": run_id}],
                partition_key=user_id,
            )
        )
    except RuntimeError:
        return _error(503, "Catalogue temporarily unavailable")
    except Exception:
        logger.exception("Cosmos query failed for catalogue by run")
        return _error(503, "Catalogue temporarily unavailable")

    return _json_response(_catalogue_list_body(docs, len(docs), 0, len(docs)))


# ---------------------------------------------------------------------------
# GET /api/catalogue/aoi/{aoiName} — time-series for an AOI
# ---------------------------------------------------------------------------


@app.function_name("catalogue_by_aoi")
@app.route(
    route="catalogue/aoi/{aoiName}",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
def catalogue_by_aoi(req: func.HttpRequest) -> func.HttpResponse:
    """List acquisition history for a specific AOI (time-series)."""
    try:
        claims = _parse_client_principal(req)
    except ValueError:
        return _error(401, "Unauthorized")
    user_id: str = claims.get("sub", "")
    if not user_id:
        return _error(401, "Missing user identity")

    aoi_name = req.route_params.get("aoiName", "")
    if not aoi_name:
        return _error(400, "Missing aoiName")

    limit = _parse_int_param((req.params or {}).get("limit", ""), 20, 1, _CATALOGUE_MAX_LIMIT)

    try:
        container = _get_cosmos_container(_CATALOGUE_CONTAINER)
        docs = list(
            container.query_items(
                query=(
                    "SELECT * FROM c WHERE c.aoi_name = @aoi"
                    " ORDER BY c.submitted_at DESC"
                    " OFFSET 0 LIMIT @lim"
                ),
                parameters=[
                    {"name": "@aoi", "value": aoi_name},
                    {"name": "@lim", "value": limit},
                ],
                partition_key=user_id,
            )
        )
    except RuntimeError:
        return _error(503, "Catalogue temporarily unavailable")
    except Exception:
        logger.exception("Cosmos query failed for catalogue by AOI")
        return _error(503, "Catalogue temporarily unavailable")

    return _json_response(_catalogue_list_body(docs, len(docs), 0, limit))

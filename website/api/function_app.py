"""SWA managed API functions — lightweight, always-warm endpoints.

These functions run inside the Static Web App's managed function runtime.
They handle user-interactive requests (SAS token minting, status polling,
billing status/checkout/portal) so the main Container Apps function app
can scale to zero without affecting UX.

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

"""Configuration loading and validation (§8 of SYSTEM_SPEC)."""

from __future__ import annotations

import os
from typing import Any

from treesight.constants import (
    DEFAULT_AOI_BUFFER_M,
    DEFAULT_AOI_MAX_AREA_HA,
    DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT,
    DEFAULT_IMAGERY_RESOLUTION_TARGET_M,
    DEFAULT_INPUT_CONTAINER,
    DEFAULT_OUTPUT_CONTAINER,
)
from treesight.errors import ConfigValidationError


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.lower() in ("true", "1", "yes")


def config_get_int(d: dict[str, Any], key: str, default: int) -> int:
    """Defensive integer coercion (§8.7)."""
    val = d.get(key)
    if val is None:
        return default
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if val != int(val):
            raise ValueError(f"Non-integer float value for {key!r}: {val!r}")
        return int(val)
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            raise ValueError(f"Non-integer string value for {key!r}: {val!r}") from None
    return default


# --- Pipeline configuration ---

IMAGERY_PROVIDER = _env("IMAGERY_PROVIDER", "planetary_computer")
IMAGERY_RESOLUTION_TARGET_M = _env_float(
    "IMAGERY_RESOLUTION_TARGET_M", DEFAULT_IMAGERY_RESOLUTION_TARGET_M
)
IMAGERY_MAX_CLOUD_COVER_PCT = _env_float(
    "IMAGERY_MAX_CLOUD_COVER_PCT", DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT
)
AOI_BUFFER_M = _env_float("AOI_BUFFER_M", DEFAULT_AOI_BUFFER_M)
AOI_MAX_AREA_HA = _env_float("AOI_MAX_AREA_HA", DEFAULT_AOI_MAX_AREA_HA)

INPUT_CONTAINER = _env("DEFAULT_INPUT_CONTAINER", DEFAULT_INPUT_CONTAINER)
OUTPUT_CONTAINER = _env("DEFAULT_OUTPUT_CONTAINER", DEFAULT_OUTPUT_CONTAINER)

# Security
KEY_VAULT_URI = _env("KEY_VAULT_URI") or _env("KEYVAULT_URL")
STORAGE_CONNECTION_STRING = _env("AzureWebJobsStorage")
STORAGE_ACCOUNT_NAME = _env("AzureWebJobsStorage__accountName")
APPINSIGHTS_CONNECTION_STRING = _env("APPLICATIONINSIGHTS_CONNECTION_STRING")
DEMO_VALET_TOKEN_SECRET = _env("DEMO_VALET_TOKEN_SECRET")
DEMO_VALET_TOKEN_TTL_SECONDS = _env_int("DEMO_VALET_TOKEN_TTL_SECONDS", 86400)
DEMO_VALET_TOKEN_MAX_USES = _env_int("DEMO_VALET_TOKEN_MAX_USES", 3)

# Authentication
# Bearer JWT auth via CIAM. Protected endpoints require an Authorization
# header with a valid bearer token.
REQUIRE_AUTH = _env_bool("REQUIRE_AUTH", False)

# Auth mode is now single-path only: bearer_only.
AUTH_MODE = _env("AUTH_MODE", "bearer_only").strip().lower() or "bearer_only"

# CIAM-native bearer JWT config (#709).
CIAM_AUTHORITY = _env("CIAM_AUTHORITY")
CIAM_TENANT_ID = _env("CIAM_TENANT_ID")
CIAM_API_AUDIENCE = _env("CIAM_API_AUDIENCE")
CIAM_JWT_LEEWAY_SECONDS = _env_int("CIAM_JWT_LEEWAY_SECONDS", 60)

# HMAC auth verification for session-token endpoints.
AUTH_HMAC_KEY = _env("AUTH_HMAC_KEY")

# Stripe billing (M4)
# In production, these resolve via @Microsoft.KeyVault() app setting references.
# Locally, leave empty to disable Stripe or set in local.settings.json for testing.
# NEVER commit real Stripe keys — they live in Key Vault only.
STRIPE_API_KEY = _env("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID_PRO_GBP = _env("STRIPE_PRICE_ID_PRO_GBP")
STRIPE_PRICE_ID_PRO_USD = _env("STRIPE_PRICE_ID_PRO_USD")
STRIPE_PRICE_ID_PRO_EUR = _env("STRIPE_PRICE_ID_PRO_EUR")

# EUDR-specific Stripe prices (#613) — base subscription + metered usage
STRIPE_PRICE_ID_EUDR_BASE_GBP = _env("STRIPE_PRICE_ID_EUDR_BASE_GBP")
STRIPE_PRICE_ID_EUDR_BASE_USD = _env("STRIPE_PRICE_ID_EUDR_BASE_USD")
STRIPE_PRICE_ID_EUDR_BASE_EUR = _env("STRIPE_PRICE_ID_EUDR_BASE_EUR")
STRIPE_PRICE_ID_EUDR_METERED_GBP = _env("STRIPE_PRICE_ID_EUDR_METERED_GBP")
STRIPE_PRICE_ID_EUDR_METERED_USD = _env("STRIPE_PRICE_ID_EUDR_METERED_USD")
STRIPE_PRICE_ID_EUDR_METERED_EUR = _env("STRIPE_PRICE_ID_EUDR_METERED_EUR")

# Cosmos DB for NoSQL (M4 state persistence)
# Auth via Managed Identity (DefaultAzureCredential) — no key needed.
COSMOS_ENDPOINT = _env("COSMOS_ENDPOINT")
COSMOS_DATABASE_NAME = _env("COSMOS_DATABASE_NAME", "treesight")

# Feature gating — restrict billing to named users while Stripe is in test mode.
# Comma-separated user IDs (sub/oid claims) that may use real billing.
# When empty, billing is gated for ALL users (everyone sees demo pricing).
BILLING_ALLOWED_USERS: frozenset[str] = frozenset(
    uid.strip() for uid in _env("BILLING_ALLOWED_USERS", "").split(",") if uid.strip()
)

# Separate operator gate for billing plan emulation (distinct from real billing access).
TIER_EMULATION_ALLOWED_USERS: frozenset[str] = frozenset(
    uid.strip() for uid in _env("TIER_EMULATION_ALLOWED_USERS", "").split(",") if uid.strip()
)


def validate_config() -> None:
    """Fail-fast startup validation (§8.6)."""
    errors: list[str] = []
    if IMAGERY_RESOLUTION_TARGET_M <= 0:
        errors.append(f"IMAGERY_RESOLUTION_TARGET_M must be > 0, got {IMAGERY_RESOLUTION_TARGET_M}")
    if not (0 <= IMAGERY_MAX_CLOUD_COVER_PCT <= 100):
        errors.append(
            f"IMAGERY_MAX_CLOUD_COVER_PCT must be 0-100, got {IMAGERY_MAX_CLOUD_COVER_PCT}"
        )
    if AOI_BUFFER_M < 0:
        errors.append(f"AOI_BUFFER_M must be >= 0, got {AOI_BUFFER_M}")
    if AOI_MAX_AREA_HA <= 0:
        errors.append(f"AOI_MAX_AREA_HA must be > 0, got {AOI_MAX_AREA_HA}")
    if AUTH_MODE != "bearer_only":
        errors.append("AUTH_MODE must be bearer_only")
    if not CIAM_AUTHORITY:
        errors.append("CIAM_AUTHORITY must be set when AUTH_MODE is bearer_only")
    if not CIAM_TENANT_ID:
        errors.append("CIAM_TENANT_ID must be set when AUTH_MODE is bearer_only")
    if not CIAM_API_AUDIENCE:
        errors.append("CIAM_API_AUDIENCE must be set when AUTH_MODE is bearer_only")
    if CIAM_JWT_LEEWAY_SECONDS < 0:
        errors.append("CIAM_JWT_LEEWAY_SECONDS must be >= 0")
    if errors:
        raise ConfigValidationError("; ".join(errors))

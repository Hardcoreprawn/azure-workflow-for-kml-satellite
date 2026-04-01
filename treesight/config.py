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
    return config_get_int({key: raw}, key, default)


def config_get_int(d: dict[str, Any], key: str, default: int) -> int:
    """Defensive integer coercion (§8.7)."""
    val = d.get(key)
    if val is None:
        return default
    if isinstance(val, int):
        return val
    if isinstance(val, (str, float)):
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default
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
APPINSIGHTS_CONNECTION_STRING = _env("APPLICATIONINSIGHTS_CONNECTION_STRING")
DEMO_VALET_TOKEN_SECRET = _env("DEMO_VALET_TOKEN_SECRET")
DEMO_VALET_TOKEN_TTL_SECONDS = _env_int("DEMO_VALET_TOKEN_TTL_SECONDS", 86400)
DEMO_VALET_TOKEN_MAX_USES = _env_int("DEMO_VALET_TOKEN_MAX_USES", 3)

# Entra External ID (CIAM) authentication
CIAM_TENANT_NAME = _env("CIAM_TENANT_NAME")
CIAM_CLIENT_ID = _env("CIAM_CLIENT_ID")
CIAM_AUDIENCE = _env("CIAM_AUDIENCE")  # defaults to CIAM_CLIENT_ID if empty
REQUIRE_AUTH = _env("REQUIRE_AUTH", "").lower() in ("true", "1", "yes")

# Stripe billing (M4)
# In production, these resolve via @Microsoft.KeyVault() app setting references.
# Locally, leave empty to disable Stripe or set in local.settings.json for testing.
# NEVER commit real Stripe keys — they live in Key Vault only.
STRIPE_API_KEY = _env("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID_PRO_GBP = _env("STRIPE_PRICE_ID_PRO_GBP")
STRIPE_PRICE_ID_PRO_USD = _env("STRIPE_PRICE_ID_PRO_USD")
STRIPE_PRICE_ID_PRO_EUR = _env("STRIPE_PRICE_ID_PRO_EUR")

# Cosmos DB for NoSQL (M4 state persistence)
# Auth via Managed Identity (DefaultAzureCredential) — no key needed.
COSMOS_ENDPOINT = _env("COSMOS_ENDPOINT")
COSMOS_DATABASE_NAME = _env("COSMOS_DATABASE_NAME", "treesight")


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
    if REQUIRE_AUTH and not (CIAM_TENANT_NAME and CIAM_CLIENT_ID):
        errors.append("REQUIRE_AUTH is set but CIAM_TENANT_NAME or CIAM_CLIENT_ID is missing")
    if errors:
        raise ConfigValidationError("; ".join(errors))

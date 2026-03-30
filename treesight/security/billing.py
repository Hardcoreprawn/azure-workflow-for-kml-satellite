"""Subscription status and plan capabilities tracked via blob storage.

Each user's billing-backed subscription state is cached in a JSON blob
``subscriptions/{user_id}.json`` inside the pipeline-payloads container.
Local-only tier emulation uses a separate blob prefix so developers can test
plan behavior without mutating the real billing record.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from treesight.constants import (
    DEMO_TIER_RUN_LIMIT,
    FREE_TIER_RUN_LIMIT,
    PIPELINE_PAYLOADS_CONTAINER,
    PRO_TIER_RUN_LIMIT,
    SUBSCRIPTIONS_PREFIX,
)

logger = logging.getLogger(__name__)

STARTER_TIER_RUN_LIMIT = 15
TEAM_TIER_RUN_LIMIT = 200
ENTERPRISE_TIER_RUN_LIMIT = 10_000

EMULATIONS_PREFIX = "subscription-emulations"

PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "demo": {
        "label": "Demo",
        "run_limit": DEMO_TIER_RUN_LIMIT,
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
        "run_limit": FREE_TIER_RUN_LIMIT,
        "aoi_limit": 5,
        "concurrency": 1,
        "ai_insights": False,
        "api_access": False,
        "export": False,
        "retention_days": 30,
        "temporal_cadence": "seasonal",
        "max_history_years": None,
        "overage_rate": None,
    },
    "starter": {
        "label": "Starter",
        "run_limit": STARTER_TIER_RUN_LIMIT,
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
        "run_limit": PRO_TIER_RUN_LIMIT,
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
        "run_limit": TEAM_TIER_RUN_LIMIT,
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
        "run_limit": ENTERPRISE_TIER_RUN_LIMIT,
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


def _blob_path(user_id: str) -> str:
    return f"{SUBSCRIPTIONS_PREFIX}/{user_id}.json"


def _emulation_blob_path(user_id: str) -> str:
    return f"{EMULATIONS_PREFIX}/{user_id}.json"


def supported_tiers() -> tuple[str, ...]:
    """Return the supported plan tiers in UI order."""
    return tuple(PLAN_CATALOG)


def normalize_tier(tier: str | None) -> str:
    """Return a supported tier name, defaulting to free."""
    candidate = (tier or "free").strip().lower()
    return candidate if candidate in PLAN_CATALOG else "free"


def plan_capabilities(tier: str | None) -> dict[str, Any]:
    """Return a serialisable plan capability payload for *tier*."""
    normalized = normalize_tier(tier)
    plan = dict(PLAN_CATALOG[normalized])
    plan["tier"] = normalized
    return plan


def get_subscription(user_id: str) -> dict[str, Any]:
    """Return cached subscription record, or a free-tier default."""
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        return storage.download_json(PIPELINE_PAYLOADS_CONTAINER, _blob_path(user_id))
    except Exception:
        return {"tier": "free", "status": "none"}


def get_subscription_emulation(user_id: str) -> dict[str, Any] | None:
    """Return a local tier-emulation record for *user_id*, if present."""
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        record = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, _emulation_blob_path(user_id))
    except Exception:
        return None

    if not record.get("enabled"):
        return None

    tier = normalize_tier(record.get("tier"))
    if tier not in PLAN_CATALOG:
        return None

    return {
        "tier": tier,
        "status": "active",
        "enabled": True,
        "updated_at": record.get("updated_at"),
    }


def save_subscription_emulation(user_id: str, tier: str) -> None:
    """Persist a tier-emulation record for local account testing."""
    from treesight.storage.client import BlobStorageClient

    normalized = normalize_tier(tier)
    if normalized not in PLAN_CATALOG:
        supported = ", ".join(supported_tiers())
        raise ValueError(f"Unsupported tier '{tier}'. Choose one of: {supported}")

    storage = BlobStorageClient()
    record = {
        "enabled": True,
        "tier": normalized,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    storage.upload_json(PIPELINE_PAYLOADS_CONTAINER, _emulation_blob_path(user_id), record)


def clear_subscription_emulation(user_id: str) -> None:
    """Disable any previously saved tier emulation for *user_id*."""
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    record = {
        "enabled": False,
        "tier": "",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    storage.upload_json(PIPELINE_PAYLOADS_CONTAINER, _emulation_blob_path(user_id), record)


def get_effective_subscription(user_id: str) -> dict[str, Any]:
    """Return the billing record overlaid with any active emulation."""
    subscription = dict(get_subscription(user_id))
    emulation = get_subscription_emulation(user_id)
    if not emulation:
        subscription["emulated"] = False
        return subscription

    effective = dict(subscription)
    effective.update(
        {
            "tier": emulation["tier"],
            "status": emulation["status"],
            "emulated": True,
            "billing_tier": normalize_tier(subscription.get("tier")),
            "billing_status": subscription.get("status", "none"),
            "emulation_updated_at": emulation.get("updated_at"),
        }
    )
    return effective


def save_subscription(user_id: str, record: dict[str, Any]) -> None:
    """Persist subscription record to blob storage."""
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    record["updated_at"] = datetime.now(UTC).isoformat()
    storage.upload_json(PIPELINE_PAYLOADS_CONTAINER, _blob_path(user_id), record)
    logger.info(
        "Subscription saved user=%s tier=%s status=%s",
        user_id,
        record.get("tier"),
        record.get("status"),
    )


def get_run_limit(user_id: str) -> int:
    """Return the pipeline run limit for a user based on their subscription tier."""
    sub = get_effective_subscription(user_id)
    tier = normalize_tier(sub.get("tier"))
    if tier == "free":
        return plan_capabilities("free")["run_limit"]
    if sub.get("status") == "active":
        return plan_capabilities(tier)["run_limit"]
    return plan_capabilities("free")["run_limit"]


def is_pro(user_id: str) -> bool:
    """Check whether a user has an active Pro subscription."""
    sub = get_effective_subscription(user_id)
    return sub.get("tier") == "pro" and sub.get("status") == "active"

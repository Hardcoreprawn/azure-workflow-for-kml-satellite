"""Stripe subscription status tracked via blob storage.

Each user's subscription state is cached in a JSON blob
``subscriptions/{user_id}.json`` inside the pipeline-payloads container.
The webhook handler writes this blob; quota checks read it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from treesight.constants import (
    FREE_TIER_RUN_LIMIT,
    PIPELINE_PAYLOADS_CONTAINER,
    PRO_TIER_RUN_LIMIT,
    SUBSCRIPTIONS_PREFIX,
)

logger = logging.getLogger(__name__)


def _blob_path(user_id: str) -> str:
    return f"{SUBSCRIPTIONS_PREFIX}/{user_id}.json"


def get_subscription(user_id: str) -> dict[str, Any]:
    """Return cached subscription record, or a free-tier default."""
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        return storage.download_json(PIPELINE_PAYLOADS_CONTAINER, _blob_path(user_id))
    except Exception:
        return {"tier": "free", "status": "none"}


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
    sub = get_subscription(user_id)
    if sub.get("tier") == "pro" and sub.get("status") == "active":
        return PRO_TIER_RUN_LIMIT
    return FREE_TIER_RUN_LIMIT


def is_pro(user_id: str) -> bool:
    """Check whether a user has an active Pro subscription."""
    sub = get_subscription(user_id)
    return sub.get("tier") == "pro" and sub.get("status") == "active"

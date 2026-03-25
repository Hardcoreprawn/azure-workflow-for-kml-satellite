"""Per-user pipeline run quota backed by blob storage.

Each user gets a fixed number of pipeline runs based on their subscription tier.
Usage is tracked in a JSON blob ``quotas/{user_id}.json`` inside the
pipeline-payloads container.  Paid tiers are resolved via the billing module.
"""

from __future__ import annotations

import logging
from typing import Any

from treesight.constants import FREE_TIER_RUN_LIMIT, PIPELINE_PAYLOADS_CONTAINER

logger = logging.getLogger(__name__)

#: Maximum free pipeline runs per user (kept for backwards compat).
FREE_TIER_LIMIT = FREE_TIER_RUN_LIMIT

_QUOTA_PREFIX = "quotas"


def _blob_path(user_id: str) -> str:
    return f"{_QUOTA_PREFIX}/{user_id}.json"


def _run_limit(user_id: str) -> int:
    """Return the run limit for a user, checking subscription tier."""
    try:
        from treesight.security.billing import get_run_limit

        return get_run_limit(user_id)
    except ImportError:
        logger.debug("Billing module not available, using free tier limit")
        return FREE_TIER_LIMIT
    except Exception:
        logger.exception("Error checking subscription tier for user=%s", user_id)
        return FREE_TIER_LIMIT


def check_quota(user_id: str) -> int:
    """Return remaining pipeline runs for *user_id*.

    Returns the tier-appropriate limit if no usage record exists yet.
    """
    from treesight.storage.client import BlobStorageClient

    limit = _run_limit(user_id)
    storage = BlobStorageClient()
    try:
        record = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, _blob_path(user_id))
        used = record.get("used", 0)
    except Exception:
        used = 0
    return max(limit - used, 0)


def consume_quota(user_id: str) -> int:
    """Increment usage and return remaining runs (after this one).

    Raises ``ValueError`` if the user has exhausted their quota.
    """
    from treesight.storage.client import BlobStorageClient

    limit = _run_limit(user_id)
    storage = BlobStorageClient()
    path = _blob_path(user_id)

    try:
        record: dict[str, Any] = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, path)
    except Exception:
        record = {"used": 0, "runs": []}

    used: int = record.get("used", 0)
    if used >= limit:
        raise ValueError(f"Quota exhausted ({limit} pipeline runs). Please upgrade to continue.")

    record["used"] = used + 1
    record.setdefault("runs", [])
    storage.upload_json(PIPELINE_PAYLOADS_CONTAINER, path, record)
    remaining = limit - record["used"]
    logger.info(
        "Quota consumed user=%s used=%d remaining=%d limit=%d",
        user_id,
        record["used"],
        remaining,
        limit,
    )
    return remaining

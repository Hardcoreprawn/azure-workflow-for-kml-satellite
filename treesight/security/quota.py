"""Per-user pipeline run quota.

Each user gets a fixed number of pipeline runs based on their subscription tier.
When Cosmos DB is configured, quota is stored in the ``users`` container.
Falls back to blob storage at ``quotas/{user_id}.json`` inside
pipeline-payloads.
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


def _get_quota_record(user_id: str) -> dict[str, Any]:
    """Load the quota record from Cosmos (users container) or blob storage."""
    from treesight.storage.cosmos_or_blob import read_with_fallback

    def _cosmos():
        from treesight.storage.cosmos import read_item

        doc = read_item("users", user_id, user_id)
        if doc:
            return doc.get("quota", {"used": 0, "runs": []})
        return {"used": 0, "runs": []}

    def _blob():
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient()
        try:
            return storage.download_json(PIPELINE_PAYLOADS_CONTAINER, _blob_path(user_id))
        except Exception:
            return {"used": 0, "runs": []}

    return read_with_fallback(_cosmos, _blob)


def _save_quota_record(user_id: str, record: dict[str, Any]) -> None:
    """Persist the quota record to Cosmos (users container) or blob storage."""
    from treesight.storage.cosmos_or_blob import write_with_fallback

    def _cosmos():
        from treesight.storage.cosmos import read_item, upsert_item

        existing = read_item("users", user_id, user_id) or {}
        existing.update({"id": user_id, "user_id": user_id, "quota": record})
        upsert_item("users", existing)

    def _blob():
        from treesight.storage.client import BlobStorageClient

        storage = BlobStorageClient()
        storage.upload_json(PIPELINE_PAYLOADS_CONTAINER, _blob_path(user_id), record)

    write_with_fallback(_cosmos, _blob)


def check_quota(user_id: str) -> int:
    """Return remaining pipeline runs for *user_id*.

    Returns the tier-appropriate limit if no usage record exists yet.
    """
    limit = _run_limit(user_id)
    record = _get_quota_record(user_id)
    used = record.get("used", 0)
    return max(limit - used, 0)


def get_usage(user_id: str) -> dict[str, Any]:
    """Return usage stats for *user_id*.

    Returns a dict with ``used`` (int) and ``limit`` (int).
    """
    limit = _run_limit(user_id)
    record = _get_quota_record(user_id)
    used = record.get("used", 0)
    return {"used": used, "limit": limit}


def consume_quota(user_id: str) -> int:
    """Increment usage and return remaining runs (after this one).

    Raises ``ValueError`` if the user has exhausted their quota.

    .. warning::

        The read/increment/write cycle is **not atomic**.  Concurrent
        requests for the same user may over-count or under-count.
    """
    # TODO: use Cosmos stored procedure for atomic quota increment
    limit = _run_limit(user_id)
    record = _get_quota_record(user_id)

    used: int = record.get("used", 0)
    if used >= limit:
        raise ValueError(f"Quota exhausted ({limit} pipeline runs). Please upgrade to continue.")

    record["used"] = used + 1
    record.setdefault("runs", [])
    _save_quota_record(user_id, record)
    remaining = limit - record["used"]
    logger.info(
        "Quota consumed user=%s used=%d remaining=%d limit=%d",
        user_id,
        record["used"],
        remaining,
        limit,
    )
    return remaining


def release_quota(user_id: str, *, instance_id: str = "") -> int:
    """Decrement usage (refund) and return remaining runs.

    Used to compensate for a failed pipeline run that was billed upfront.
    Idempotent when *instance_id* is provided — repeated calls for the
    same instance are no-ops to handle Durable Functions at-least-once
    activity delivery.
    """
    limit = _run_limit(user_id)
    record = _get_quota_record(user_id)

    # Idempotency guard: skip if this instance was already refunded.
    refunded: list[str] = record.get("refunded", [])
    if instance_id and instance_id in refunded:
        logger.info(
            "Quota already released for instance=%s user=%s — skipping",
            instance_id,
            user_id,
        )
        used = record.get("used", 0)
        return max(limit - used, 0)

    used: int = record.get("used", 0)
    new_used = used - 1 if used > 0 else 0
    record["used"] = new_used
    if instance_id:
        refunded.append(instance_id)
        record["refunded"] = refunded
    _save_quota_record(user_id, record)
    remaining = limit - new_used
    logger.info(
        "Quota released user=%s used=%d remaining=%d limit=%d instance=%s",
        user_id,
        new_used,
        remaining,
        limit,
        instance_id,
    )
    return remaining

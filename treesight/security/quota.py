"""Per-user pipeline run quota.

Each user gets a fixed number of pipeline runs based on their subscription tier.
Quota records are stored in the Cosmos DB ``users`` container with partition
key ``/user_id``.
"""

from __future__ import annotations

import logging
from typing import Any

from treesight.constants import FREE_TIER_RUN_LIMIT

logger = logging.getLogger(__name__)

#: Maximum free pipeline runs per user (kept for backwards compat).
FREE_TIER_LIMIT = FREE_TIER_RUN_LIMIT

#: Maximum optimistic-concurrency retries for ``consume_quota``.
MAX_QUOTA_ETAG_RETRIES = 5


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
    """Load the quota record from Cosmos (users container)."""
    from treesight.storage.cosmos import read_item

    doc = read_item("users", user_id, user_id)
    if doc:
        return doc.get("quota", {"used": 0, "runs": []})
    return {"used": 0, "runs": []}


def _save_quota_record(
    user_id: str,
    record: dict[str, Any],
    *,
    preserve_higher_used: bool = False,
) -> None:
    """Persist the quota record to Cosmos (users container)."""
    from treesight.storage.cosmos import read_item, upsert_item

    existing = read_item("users", user_id, user_id) or {}
    existing_quota_raw = existing.get("quota")
    existing_quota: dict[str, Any] = (
        existing_quota_raw if isinstance(existing_quota_raw, dict) else {}
    )
    merged_quota: dict[str, Any] = dict(existing_quota)
    merged_quota.update(record)
    incoming_used = int(record.get("used", 0))
    if preserve_higher_used:
        merged_quota["used"] = max(int(existing_quota.get("used", 0)), incoming_used)
    else:
        merged_quota["used"] = incoming_used
    existing_runs = existing_quota.get("runs", [])
    record_runs = record.get("runs", [])
    if isinstance(existing_runs, list) and isinstance(record_runs, list):
        merged_quota["runs"] = (
            existing_runs if len(existing_runs) >= len(record_runs) else record_runs
        )

    existing.update({"id": user_id, "user_id": user_id, "quota": merged_quota})
    from treesight.models.records import UserRecord

    UserRecord.model_validate(existing)
    upsert_item("users", existing)


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
    """
    from treesight.models.records import UserRecord
    from treesight.storage.cosmos import (
        EtagPreconditionFailedError,
        read_item_with_etag,
        replace_item_with_etag,
    )

    limit = _run_limit(user_id)
    last_error: Exception | None = None

    for _ in range(MAX_QUOTA_ETAG_RETRIES):
        loaded = read_item_with_etag("users", user_id, user_id)
        if not loaded:
            _save_quota_record(
                user_id,
                {"used": 0, "runs": []},
                preserve_higher_used=True,
            )
            loaded = read_item_with_etag("users", user_id, user_id)
            if not loaded:
                logger.debug("consume_quota bootstrap race user=%s", user_id)
                continue
        user_doc, etag = loaded

        record = user_doc.get("quota", {"used": 0, "runs": []})
        used = int(record.get("used", 0))
        if used >= limit:
            raise ValueError(
                f"Quota exhausted ({limit} pipeline runs). Please upgrade to continue."
            )

        record["used"] = used + 1
        record.setdefault("runs", [])
        user_doc.update({"id": user_id, "user_id": user_id, "quota": record})
        # Defensive schema check before committing the conditional write.
        _ = UserRecord.model_validate(user_doc)

        try:
            replace_item_with_etag("users", user_doc, etag=etag)
        except EtagPreconditionFailedError as exc:
            last_error = exc
            logger.debug("consume_quota etag conflict user=%s", user_id)
            continue

        remaining = limit - record["used"]
        logger.info(
            "Quota consumed user=%s used=%d remaining=%d limit=%d",
            user_id,
            record["used"],
            remaining,
            limit,
        )
        return remaining

    raise RuntimeError(
        f"consume_quota user={user_id}: {MAX_QUOTA_ETAG_RETRIES} etag retries exhausted "
        f"(last={last_error})"
    )


def release_quota(user_id: str, *, instance_id: str = "") -> int:
    """Decrement usage (refund) and return remaining runs.

    Used to compensate for a failed pipeline run that was billed upfront.
    Idempotent when *instance_id* is provided — repeated calls for the
    same instance are no-ops to handle Durable Functions at-least-once
    activity delivery.

    Uses optimistic concurrency (etag) so concurrent refunds cannot
    race and double-decrement the same counter.
    """
    from treesight.models.records import UserRecord
    from treesight.storage.cosmos import (
        EtagPreconditionFailedError,
        read_item_with_etag,
        replace_item_with_etag,
    )

    limit = _run_limit(user_id)
    last_error: Exception | None = None

    for _ in range(MAX_QUOTA_ETAG_RETRIES):
        loaded = read_item_with_etag("users", user_id, user_id)
        if not loaded:
            # No quota record — nothing to release; return full quota.
            remaining = limit
            logger.info(
                "Quota released (no record) user=%s remaining=%d limit=%d instance=%s",
                user_id,
                remaining,
                limit,
                instance_id,
            )
            return remaining

        user_doc, etag = loaded
        record = user_doc.get("quota", {"used": 0, "runs": []})

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

        user_doc.update({"id": user_id, "user_id": user_id, "quota": record})
        # Defensive schema check before committing the conditional write.
        UserRecord.model_validate(user_doc)

        try:
            replace_item_with_etag("users", user_doc, etag=etag)
        except EtagPreconditionFailedError as exc:
            last_error = exc
            logger.debug("release_quota etag conflict user=%s", user_id)
            continue

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

    raise RuntimeError(
        f"release_quota user={user_id}: {MAX_QUOTA_ETAG_RETRIES} etag retries exhausted "
        f"(last={last_error})"
    )

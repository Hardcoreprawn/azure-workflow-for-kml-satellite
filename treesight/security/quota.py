"""Per-user pipeline run quota backed by blob storage.

Each user gets a fixed number of free pipeline runs.  Usage is tracked in
a JSON blob ``quotas/{user_id}.json`` inside the pipeline-payloads container.
"""

from __future__ import annotations

import logging

from treesight.constants import PIPELINE_PAYLOADS_CONTAINER

logger = logging.getLogger(__name__)

#: Maximum free pipeline runs per user.
FREE_TIER_LIMIT = 5

_QUOTA_PREFIX = "quotas"


def _blob_path(user_id: str) -> str:
    return f"{_QUOTA_PREFIX}/{user_id}.json"


def check_quota(user_id: str) -> int:
    """Return remaining pipeline runs for *user_id*.

    Returns ``FREE_TIER_LIMIT`` if no usage record exists yet.
    """
    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    try:
        record = storage.download_json(PIPELINE_PAYLOADS_CONTAINER, _blob_path(user_id))
        used = record.get("used", 0)
    except Exception:
        used = 0
    return max(FREE_TIER_LIMIT - used, 0)


def consume_quota(user_id: str) -> int:
    """Increment usage and return remaining runs (after this one).

    Uses ETag-based optimistic concurrency to prevent TOCTOU races.
    Raises ``ValueError`` if the user has exhausted their free quota.
    """
    from azure.core.exceptions import ResourceModifiedError

    from treesight.storage.client import BlobStorageClient

    storage = BlobStorageClient()
    path = _blob_path(user_id)

    max_retries = 3
    for attempt in range(max_retries):
        etag: str | None = None
        try:
            record, etag = storage.download_json_with_etag(PIPELINE_PAYLOADS_CONTAINER, path)
        except Exception:
            record = {"used": 0, "runs": []}

        used: int = record.get("used", 0)
        if used >= FREE_TIER_LIMIT:
            raise ValueError(
                f"Free quota exhausted ({FREE_TIER_LIMIT} runs). Please upgrade to continue."
            )

        record["used"] = used + 1
        record.setdefault("runs", [])

        if etag:
            try:
                storage.upload_json_if_match(PIPELINE_PAYLOADS_CONTAINER, path, record, etag)
            except ResourceModifiedError:
                if attempt < max_retries - 1:
                    logger.warning("Quota update conflict for user=%s, retrying", user_id)
                    continue
                raise ValueError("Quota update conflict — please retry") from None
        else:
            # New record — no ETag to match
            storage.upload_json(PIPELINE_PAYLOADS_CONTAINER, path, record)

        remaining = FREE_TIER_LIMIT - record["used"]
        logger.info(
            "Quota consumed user=%s used=%d remaining=%d", user_id, record["used"], remaining
        )
        return remaining

    raise ValueError("Quota update failed — please retry")

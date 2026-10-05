"""Authoritative run lookup and originating-organisation access policy."""

from __future__ import annotations

import logging
from typing import Any

from treesight.storage import cosmos

logger = logging.getLogger(__name__)


class RunRecordLookupError(RuntimeError):
    """Raised when a run record lookup fails due to backend availability/errors."""


def get_run_record_by_instance_id(instance_id: str, *, raise_on_error: bool = False) -> dict[str, Any] | None:
    """Read a run across partitions; strict mode distinguishes outages from absence."""
    if not cosmos.cosmos_available():
        if raise_on_error:
            raise RunRecordLookupError("Cosmos unavailable")
        return None
    try:
        results = cosmos.query_items(
            "runs",
            "SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": instance_id}],
        )
        return results[0] if results else None
    except Exception as exc:
        logger.warning("Cosmos run lookup failed for instance=%s", instance_id, exc_info=True)
        if raise_on_error:
            raise RunRecordLookupError("Run lookup failed") from exc
        return None


def assert_run_write_access(
    run_record: dict[str, Any], requesting_user_id: str, *, active_org: dict[str, Any] | None = None
) -> None:
    """Require current membership in the run's immutable originating organisation."""
    org_id = run_record.get("org_id")
    if isinstance(org_id, str) and org_id.strip() and active_org and active_org.get("org_id") == org_id:
        members = active_org.get("members", [])
        if isinstance(members, list) and any(
            isinstance(member, dict) and member.get("user_id") == requesting_user_id for member in members
        ):
            return
    raise ValueError("Run not found or you do not have permission to modify it")

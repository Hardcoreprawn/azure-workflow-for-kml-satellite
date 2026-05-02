"""Concurrency cap helpers — bound active pipeline runs (#759).

Counts Cosmos records with an active status and compares against
MAX_CONCURRENT_JOBS. Stale jobs (older than MAX_JOB_DURATION_MINUTES)
are excluded from the count so a crashed run does not permanently block
new submissions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)


def count_active_runs(container_name: str = "run-records") -> int:
    """Return the number of active pipeline runs in Cosmos.

    A run is considered active when its ``status`` is ``submitted``,
    ``running``, or ``queued`` *and* its ``submitted_at`` is within the
    stale-job window (``MAX_JOB_DURATION_MINUTES``).

    Returns 0 when Cosmos is unavailable so a storage outage never
    hard-blocks new submissions via this path.
    """
    from treesight import config
    from treesight.constants import ACTIVE_RUN_STATUSES
    from treesight.storage import cosmos as _cosmos

    if not _cosmos.cosmos_available():
        return 0

    window_minutes = config.MAX_JOB_DURATION_MINUTES
    cutoff = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()

    # Build an IN filter for ACTIVE_RUN_STATUSES.
    status_placeholders = ", ".join(f"@s{i}" for i in range(len(ACTIVE_RUN_STATUSES)))
    params: list[dict] = [
        {"name": f"@s{i}", "value": s}
        for i, s in enumerate(sorted(ACTIVE_RUN_STATUSES))
    ]
    params.append({"name": "@cutoff", "value": cutoff})

    # status_placeholders come from a constant frozenset — no user input involved.
    # Values are fully parameterized; only placeholder names are interpolated.
    query = (
        "SELECT VALUE COUNT(1) FROM c WHERE c.status IN ("  # noqa: S608
        + status_placeholders
        + ") AND c.submitted_at >= @cutoff"
    )

    try:
        rows = _cosmos.query_items(container_name, query, parameters=params)
        return int(rows[0]) if rows else 0
    except Exception:
        logger.exception("count_active_runs query failed — treating as 0")
        return 0


def at_concurrency_cap(container_name: str = "run-records") -> bool:
    """Return True when active run count is at or above MAX_CONCURRENT_JOBS."""
    from treesight import config

    cap = config.MAX_CONCURRENT_JOBS
    if cap <= 0:
        return False
    return count_active_runs(container_name) >= cap

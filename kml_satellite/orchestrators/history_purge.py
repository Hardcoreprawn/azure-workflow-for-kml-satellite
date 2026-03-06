"""Durable orchestration history purge planning.

Provides deterministic, testable policy logic for selecting which
orchestration instances should be purged by the scheduled maintenance
function.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DEFAULT_RETENTION_DAYS = 14
MAX_RETENTION_DAYS = 3650
DEFAULT_PURGE_STATUSES = ("Completed", "Failed", "Terminated")
_ALLOWED_STATUSES = {
    "Completed",
    "Failed",
    "Terminated",
    "Canceled",
    "ContinuedAsNew",
}


@dataclass(frozen=True, slots=True)
class PurgePlan:
    """Resolved purge policy window and runtime statuses."""

    created_time_from: datetime
    created_time_to: datetime
    runtime_statuses: list[str]
    retention_days: int


def parse_retention_days(raw_value: str | None) -> int:
    """Parse retention days with defensive bounds checking."""
    if raw_value is None or not raw_value.strip():
        return DEFAULT_RETENTION_DAYS

    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_RETENTION_DAYS

    if value < 1:
        return DEFAULT_RETENTION_DAYS

    if value > MAX_RETENTION_DAYS:
        return MAX_RETENTION_DAYS

    return value


def parse_purge_statuses(raw_value: str | None) -> list[str]:
    """Parse configured statuses into a safe, deduplicated status list."""
    if raw_value is None or not raw_value.strip():
        return list(DEFAULT_PURGE_STATUSES)

    parsed: list[str] = []
    seen: set[str] = set()

    for token in raw_value.split(","):
        normalized = token.strip()
        if not normalized:
            continue

        # Accept case-insensitive values and normalize to durable status casing.
        canonical = normalized[0:1].upper() + normalized[1:].lower()
        if canonical not in _ALLOWED_STATUSES:
            continue

        if canonical in seen:
            continue

        seen.add(canonical)
        parsed.append(canonical)

    if not parsed:
        return list(DEFAULT_PURGE_STATUSES)

    return parsed


def build_purge_plan(
    *,
    now_utc: datetime,
    retention_days_raw: str | None,
    statuses_raw: str | None,
) -> PurgePlan:
    """Build a deterministic purge plan from runtime configuration.

    The plan purges instances created from Unix epoch up to (now - retention).
    """
    retention_days = parse_retention_days(retention_days_raw)
    cutoff = now_utc - timedelta(days=retention_days)

    return PurgePlan(
        created_time_from=datetime(1970, 1, 1, tzinfo=UTC),
        created_time_to=cutoff,
        runtime_statuses=parse_purge_statuses(statuses_raw),
        retention_days=retention_days,
    )

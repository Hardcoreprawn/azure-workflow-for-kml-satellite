"""EUDR billing and usage data assembly.

Pure functions: assemble usage payloads and fetch org records.
No HTTP or Azure Functions dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def parse_iso_datetime(value: str) -> datetime | None:
    """Parse an ISO 8601 datetime string, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def month_key(dt: datetime) -> str:
    """Return a ``YYYY-MM`` key for the given datetime."""
    return dt.strftime("%Y-%m")


def last_n_month_keys(n: int, *, now: datetime | None = None) -> list[str]:
    """Return ``n`` consecutive ``YYYY-MM`` keys ending at *now*."""
    now = now or datetime.now(UTC)
    y = now.year
    m = now.month
    keys: list[str] = []
    for _ in range(n):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    keys.reverse()
    return keys


def org_member_ids_for_user(user_id: str) -> list[str]:
    """Return the list of member user IDs for the user's org, falling back to ``[user_id]``."""
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return [user_id]
    members = org.get("members", [])
    member_ids: list[str] = []
    for member in members:
        if isinstance(member, dict):
            mid = str(member.get("user_id", "")).strip()
            if mid and mid not in member_ids:
                member_ids.append(mid)
    if user_id not in member_ids:
        member_ids.append(user_id)
    return member_ids


def eudr_usage_payload(user_id: str, records: list[dict] | None = None) -> dict[str, Any]:
    """Assemble the EUDR usage dashboard payload for *user_id*.

    *records* is a pre-fetched list of run records (for testability).
    When omitted the caller is responsible for injecting data via the
    blueprint layer, which owns the ``_fetch_submission_records`` dependency.
    """
    from treesight.constants import EUDR_INCLUDED_PARCELS
    from treesight.security.eudr_billing import (
        eudr_graduated_overage_gbp,
        eudr_next_tier,
        get_eudr_billing_status,
    )
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    org_id = org.get("org_id") if isinstance(org, dict) else ""
    billing = get_eudr_billing_status(org_id or "", user_id=user_id)

    period_used = int(billing.get("period_parcels_used", 0) or 0)
    included = int(billing.get("included_parcels", EUDR_INCLUDED_PARCELS) or EUDR_INCLUDED_PARCELS)
    overage_parcels = max(period_used - included, 0)

    next_threshold, next_rate = eudr_next_tier(period_used)

    run_records: list[dict] = records if records is not None else []
    month_keys = last_n_month_keys(6)
    by_month: dict[str, dict[str, int]] = {k: {"parcels": 0, "runs": 0, "overage_runs": 0} for k in month_keys}
    for record in run_records:
        submitted = parse_iso_datetime(str(record.get("submitted_at", "")))
        if not submitted:
            continue
        key = month_key(submitted)
        if key not in by_month:
            continue
        by_month[key]["runs"] += 1
        by_month[key]["parcels"] += int(record.get("aoi_count", 0) or 0)
        if str(record.get("billing_type", "")) == "overage":
            by_month[key]["overage_runs"] += 1

    months = [
        {
            "month": key,
            "runs": by_month[key]["runs"],
            "parcels": by_month[key]["parcels"],
            "overageRuns": by_month[key]["overage_runs"],
        }
        for key in month_keys
    ]

    # Graduated tiered calculation so parcels 11–100 are charged at £3,
    # 101–500 at £2.50, and 501+ at £1.80.
    estimated_spend_gbp = eudr_graduated_overage_gbp(period_used, included)

    return {
        "current": {
            "periodParcelsUsed": period_used,
            "includedParcels": included,
            "overageParcels": overage_parcels,
            "estimatedSpendGbp": estimated_spend_gbp,
            "nextTierThreshold": next_threshold,
            "nextTierRateGbp": next_rate,
            "parcelsToNextTier": (next_threshold - period_used) if next_threshold else 0,
            "within20PercentOfNextTier": bool(next_threshold and period_used >= int(next_threshold * 0.8)),
        },
        "history": months,
    }

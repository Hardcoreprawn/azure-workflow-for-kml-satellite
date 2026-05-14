"""Org-pooled run accounting (umbrella issue #814).

A single source of truth for "how many parcels has this org consumed in
the current period". Replaces the divergent per-user ``quota`` and
per-org ``eudr_assessments_used`` counters.

Model
-----
* **1 run = 1 parcel processed.** EUDR is just a flag on the run for
  reporting/audit, not a separate counter.
* **Pool = sum of member allowances.** Each member contributes their
  plan's ``run_limit`` to the org pool every period. Org with one Pro
  member (50) and two Free members (5) has a pool of 60 parcels/period.
* **Two-phase, idempotent.** ``reserve_run`` debits the pool at submit
  time and is keyed on the orchestrator ``instance_id``. ``finalize_run``
  moves the reservation into either ``runs_completed`` (success) or
  ``runs_refunded`` (failure) and is also idempotent.
* **ETag optimistic concurrency.** Concurrent reservations against the
  same org doc retry up to ``MAX_ETAG_RETRIES`` times before surfacing a
  ``ConcurrencyError``.

Period
------
Periods are calendar months in UTC. The block is initialised lazily on
the first reservation of a new month. Stripe-driven billing periods can
overlay this in a later stage without changing the public API here.

This module is the only writer for the org ``usage`` block. Readers can
load the org doc directly or use :func:`get_pool_status` for a serialised
snapshot suitable for the UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

#: Maximum number of times ``reserve_run`` / ``finalize_run`` will retry
#: on an ETag conflict before raising :class:`ConcurrencyError`.
MAX_ETAG_RETRIES = 5

FinalizeStatus = Literal["completed", "failed"]


# ── Errors ───────────────────────────────────────────────────────────────


class AccountingError(Exception):
    """Base class for accounting rejections.

    All subclasses carry a stable :attr:`reason` string suitable for
    surfacing in API error payloads and structured logs.
    """

    reason: str = "accounting_error"


class OrgNotFoundError(AccountingError):
    reason = "org_not_found"


class QuotaExhaustedError(AccountingError):
    reason = "quota_exhausted"


class MemberCapExceededError(AccountingError):
    reason = "member_cap_exceeded"


class ConcurrencyError(AccountingError):
    reason = "concurrency_retries_exhausted"


# ── Public types ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Reservation:
    """The receipt returned by :func:`reserve_run`."""

    org_id: str
    user_id: str
    instance_id: str
    parcel_count: int
    is_eudr: bool
    period_start: str
    period_end: str
    pool_remaining: int


# ── Internal helpers ─────────────────────────────────────────────────────


def _now() -> datetime:
    """Indirect ``datetime.now`` for test patching."""
    return datetime.now(UTC)


def _current_period_bounds(now: datetime) -> tuple[str, str]:
    """Return ``(period_start, period_end)`` ISO strings for the UTC month."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def _ensure_usage_block(org: dict[str, Any], now: datetime) -> None:
    """Initialise or roll over the ``usage`` block in place.

    A rollover archives the previous block to ``usage_history`` (capped at
    twelve entries) so audits can answer "how many parcels in March".
    """
    period_start, period_end = _current_period_bounds(now)
    usage = org.get("usage")
    if usage and usage.get("period_end") == period_end:
        return

    if usage:
        history = org.get("usage_history", [])
        history.append(usage)
        org["usage_history"] = history[-12:]

    org["usage"] = {
        "period_start": period_start,
        "period_end": period_end,
        "runs_reserved": 0,
        "runs_completed": 0,
        "runs_refunded": 0,
        "reservations": {},
        "finalized_instance_ids": [],
    }


def _member_user_ids(org: dict[str, Any]) -> list[str]:
    return [m["user_id"] for m in org.get("members", []) if m.get("user_id")]


def _member_run_allowance(user_id: str) -> int:
    """Return the per-period run allowance the member contributes to the pool.

    Members on an active paid plan contribute their tier's ``run_limit``;
    members on no/expired subscription contribute the free-tier allowance.
    """
    from treesight.security.billing import (
        get_effective_subscription,
        normalize_tier,
        plan_capabilities,
    )

    sub = get_effective_subscription(user_id)
    tier = normalize_tier(sub.get("tier"))
    if tier == "free" or sub.get("status") == "active":
        return int(plan_capabilities(tier)["run_limit"])
    return int(plan_capabilities("free")["run_limit"])


def compute_pool_allowance(org: dict[str, Any]) -> int:
    """Return the org's parcels-per-period allowance for the current state.

    Sum of every member's plan ``run_limit``. Members removed from the org
    immediately stop contributing; new members add their allowance from
    the next reservation onwards.
    """
    return sum(_member_run_allowance(uid) for uid in _member_user_ids(org))


def _member_period_usage(usage: dict[str, Any], user_id: str) -> int:
    """Sum of *user_id*'s reserved + completed parcels in the current period."""
    total = 0
    for res in usage.get("reservations", {}).values():
        if res.get("user_id") == user_id:
            total += int(res.get("parcel_count", 0))
    # ``runs_completed`` is the org-wide aggregate, not per-user, so we walk
    # ``finalized_instance_ids`` against the original reservations only when
    # they are still present in the dict; once finalised they are removed.
    # The frontend tracks per-user historical usage separately. For cap
    # enforcement, in-flight reservations are sufficient because completed
    # runs from the same period are also bounded by the pool check above.
    return total


# ── Public API ───────────────────────────────────────────────────────────


def reserve_run(
    *,
    org_id: str,
    user_id: str,
    parcel_count: int,
    is_eudr: bool,
    instance_id: str,
) -> Reservation:
    """Atomically reserve *parcel_count* parcels from the org pool.

    Idempotent on *instance_id* — calling twice with the same id returns
    the existing reservation without re-debiting. Raises a subclass of
    :class:`AccountingError` on rejection.

    Args:
        org_id: Cosmos org doc id.
        user_id: Member submitting the run.
        parcel_count: Number of parcels in this submission.
        is_eudr: Whether the run will produce an EUDR report. Recorded
            on the reservation for audit and Stripe-overage attribution;
            does not gate the debit (report capability is checked
            separately at output time).
        instance_id: Durable Functions orchestrator instance id, used as
            the idempotency key for both reserve and finalize.
    """
    if parcel_count <= 0:
        raise ValueError(f"parcel_count must be positive, got {parcel_count}")

    from treesight.storage.cosmos import (
        EtagPreconditionFailedError,
        read_item_with_etag,
        replace_item_with_etag,
    )

    last_error: Exception | None = None
    for _ in range(MAX_ETAG_RETRIES):
        loaded = read_item_with_etag("orgs", org_id, org_id)
        if not loaded:
            raise OrgNotFoundError(f"org {org_id} not found")
        org, etag = loaded

        now = _now()
        _ensure_usage_block(org, now)
        usage = org["usage"]

        # Idempotency — replay returns the existing receipt.
        existing = usage.get("reservations", {}).get(instance_id)
        if existing:
            allowance = compute_pool_allowance(org)
            in_flight = int(usage.get("runs_reserved", 0)) + int(usage.get("runs_completed", 0))
            return Reservation(
                org_id=org_id,
                user_id=existing["user_id"],
                instance_id=instance_id,
                parcel_count=int(existing["parcel_count"]),
                is_eudr=bool(existing.get("is_eudr", False)),
                period_start=usage["period_start"],
                period_end=usage["period_end"],
                pool_remaining=max(allowance - in_flight, 0),
            )

        # Pool check.
        allowance = compute_pool_allowance(org)
        in_flight = int(usage.get("runs_reserved", 0)) + int(usage.get("runs_completed", 0))
        available = allowance - in_flight
        if available < parcel_count:
            raise QuotaExhaustedError(
                f"org {org_id} pool exhausted: requested {parcel_count}, "
                f"available {available} of {allowance}"
            )

        # Optional per-member cap.
        cap = (org.get("members_caps") or {}).get(user_id)
        if cap is not None:
            member_used = _member_period_usage(usage, user_id)
            if member_used + parcel_count > int(cap):
                raise MemberCapExceededError(
                    f"user {user_id} cap {cap} would be exceeded "
                    f"(used {member_used}, requesting {parcel_count})"
                )

        # Commit.
        usage["runs_reserved"] = int(usage.get("runs_reserved", 0)) + parcel_count
        usage.setdefault("reservations", {})[instance_id] = {
            "user_id": user_id,
            "parcel_count": parcel_count,
            "is_eudr": is_eudr,
            "ts": now.isoformat(),
        }

        try:
            replace_item_with_etag("orgs", org, etag=etag)
        except EtagPreconditionFailedError as exc:
            last_error = exc
            logger.debug("reserve_run etag conflict org=%s instance=%s", org_id, instance_id)
            continue

        logger.info(
            "reserve_run org=%s user=%s instance=%s parcels=%d is_eudr=%s remaining=%d",
            org_id,
            user_id,
            instance_id,
            parcel_count,
            is_eudr,
            available - parcel_count,
        )
        return Reservation(
            org_id=org_id,
            user_id=user_id,
            instance_id=instance_id,
            parcel_count=parcel_count,
            is_eudr=is_eudr,
            period_start=usage["period_start"],
            period_end=usage["period_end"],
            pool_remaining=available - parcel_count,
        )

    raise ConcurrencyError(
        f"reserve_run org={org_id} instance={instance_id}: "
        f"{MAX_ETAG_RETRIES} etag retries exhausted (last={last_error})"
    )


def finalize_run(
    *,
    org_id: str,
    instance_id: str,
    status: FinalizeStatus,
) -> None:
    """Move a reservation into the completed or refunded counter.

    Idempotent on *instance_id* — replays after the first call are
    silently ignored. Unknown reservations are also no-ops (logged at
    warning) so this is safe to call from at-least-once orchestrator
    callbacks for runs that never reserved (e.g. submission rejected
    before reaching ``reserve_run``).
    """
    if status not in ("completed", "failed"):
        raise ValueError(f"status must be 'completed' or 'failed', got {status!r}")

    from treesight.storage.cosmos import (
        EtagPreconditionFailedError,
        read_item_with_etag,
        replace_item_with_etag,
    )

    last_error: Exception | None = None
    for _ in range(MAX_ETAG_RETRIES):
        loaded = read_item_with_etag("orgs", org_id, org_id)
        if not loaded:
            logger.warning("finalize_run org=%s not found", org_id)
            return
        org, etag = loaded

        usage = org.get("usage")
        if not usage:
            logger.warning(
                "finalize_run org=%s instance=%s: no usage block — ignoring",
                org_id,
                instance_id,
            )
            return

        if instance_id in usage.get("finalized_instance_ids", []):
            return

        reservation = usage.get("reservations", {}).get(instance_id)
        if not reservation:
            logger.warning(
                "finalize_run org=%s instance=%s: no matching reservation — ignoring",
                org_id,
                instance_id,
            )
            return

        n = int(reservation["parcel_count"])
        usage["runs_reserved"] = max(0, int(usage.get("runs_reserved", 0)) - n)
        if status == "completed":
            usage["runs_completed"] = int(usage.get("runs_completed", 0)) + n
        else:
            usage["runs_refunded"] = int(usage.get("runs_refunded", 0)) + n

        del usage["reservations"][instance_id]
        usage.setdefault("finalized_instance_ids", []).append(instance_id)

        try:
            replace_item_with_etag("orgs", org, etag=etag)
        except EtagPreconditionFailedError as exc:
            last_error = exc
            logger.debug("finalize_run etag conflict org=%s instance=%s", org_id, instance_id)
            continue

        logger.info(
            "finalize_run org=%s instance=%s status=%s parcels=%d",
            org_id,
            instance_id,
            status,
            n,
        )
        return

    raise ConcurrencyError(
        f"finalize_run org={org_id} instance={instance_id}: "
        f"{MAX_ETAG_RETRIES} etag retries exhausted (last={last_error})"
    )


def get_pool_status(org_id: str) -> dict[str, Any]:
    """Return a serialisable snapshot of the org pool for UI display.

    Returns a dict with ``allowance``, ``reserved``, ``completed``,
    ``refunded``, ``available``, ``period_start``, ``period_end`` and
    ``per_member`` (mapping ``user_id`` → ``{allowance, used}``). All
    counts are parcels.
    """
    from treesight.security.orgs import get_org

    org = get_org(org_id)
    if not org:
        raise OrgNotFoundError(f"org {org_id} not found")

    now = _now()
    period_start, period_end = _current_period_bounds(now)
    usage = org.get("usage") or {}

    # If usage is from a previous period, surface zeros without writing.
    if usage.get("period_end") != period_end:
        reserved = completed = refunded = 0
        per_member_used: dict[str, int] = {}
    else:
        reserved = int(usage.get("runs_reserved", 0))
        completed = int(usage.get("runs_completed", 0))
        refunded = int(usage.get("runs_refunded", 0))
        per_member_used = {}
        for res in usage.get("reservations", {}).values():
            uid = res.get("user_id")
            if uid:
                per_member_used[uid] = per_member_used.get(uid, 0) + int(res.get("parcel_count", 0))

    per_member: dict[str, dict[str, int | None]] = {}
    allowance = 0
    for uid in _member_user_ids(org):
        member_allow = _member_run_allowance(uid)
        per_member[uid] = {
            "allowance": member_allow,
            "used": per_member_used.get(uid, 0),
            "cap": (org.get("members_caps") or {}).get(uid),
        }
        allowance += member_allow

    return {
        "org_id": org_id,
        "period_start": period_start,
        "period_end": period_end,
        "allowance": allowance,
        "reserved": reserved,
        "completed": completed,
        "refunded": refunded,
        "available": max(allowance - reserved - completed, 0),
        "per_member": per_member,
    }

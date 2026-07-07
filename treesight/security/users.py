"""User profile persistence and operator lookup.

User records live in the Cosmos ``users`` container (partition key ``/user_id``).
A user document looks like::

    {
        "id": "<swa_user_id>",
        "user_id": "<swa_user_id>",
        "email": "j.brewster@outlook.com",
        "display_name": "James Brewster",
        "identity_provider": "aad",
        "billing_allowed": true,
        "first_seen": "2026-04-13T18:00:00+00:00",
        "last_seen": "2026-04-13T19:30:00+00:00",
        "quota": { ... }       # managed by quota.py
    }

The ``billing_allowed`` flag replaces the static env-var allow-list;
operators can set it at runtime via ``POST /api/ops/users/{id}/role``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def _preserve_quota_fields(doc: dict[str, Any], latest: dict[str, Any] | None) -> None:
    """Merge quota fields from latest persisted user doc into *doc*.

    This prevents unrelated profile writes from resetting concurrently updated
    quota counters.
    """
    if not isinstance(latest, dict):
        return
    latest_quota_raw = latest.get("quota")
    if not isinstance(latest_quota_raw, dict):
        return
    latest_quota: dict[str, Any] = latest_quota_raw

    current_quota_raw = doc.get("quota")
    current_quota: dict[str, Any] = current_quota_raw if isinstance(current_quota_raw, dict) else {}
    merged_quota = dict(latest_quota)
    merged_quota.update(current_quota)
    merged_quota["used"] = max(int(latest_quota.get("used", 0)), int(current_quota.get("used", 0)))

    latest_runs = latest_quota.get("runs", [])
    current_runs = current_quota.get("runs", [])
    if (
        ("runs" in latest_quota or "runs" in current_quota)
        and isinstance(latest_runs, list)
        and isinstance(current_runs, list)
    ):
        merged_quota["runs"] = (
            latest_runs if len(latest_runs) >= len(current_runs) else current_runs
        )

    doc["quota"] = merged_quota


def record_user_sign_in(
    user_id: str,
    *,
    email: str = "",
    display_name: str = "",
    identity_provider: str = "",
) -> None:
    """Upsert a lightweight profile record on every sign-in.

    Merges into existing document so quota and subscription data
    are never overwritten.
    """
    if not user_id or user_id == "anonymous":
        return

    from treesight.storage.cosmos import cosmos_available, read_item, upsert_item

    if not cosmos_available():
        return

    try:
        existing = read_item("users", user_id, user_id) or {}
        now = datetime.now(UTC).isoformat()

        existing.setdefault("id", user_id)
        existing.setdefault("user_id", user_id)
        existing.setdefault("first_seen", now)
        existing.setdefault("created_at", now)
        existing["last_seen"] = now

        if email:
            existing["email"] = email
        if display_name:
            existing["display_name"] = display_name
        if identity_provider:
            existing["identity_provider"] = identity_provider

        from treesight.models.records import UserRecord

        UserRecord.model_validate(existing)
        latest = read_item("users", user_id, user_id)
        _preserve_quota_fields(existing, latest)
        upsert_item("users", existing)
    except Exception:
        logger.warning("Failed to record sign-in for user=%s", user_id, exc_info=True)


def get_user(user_id: str) -> dict[str, Any] | None:
    """Return the user document from Cosmos, or None."""
    from treesight.storage.cosmos import cosmos_available, read_item

    if not cosmos_available():
        return None
    try:
        return read_item("users", user_id, user_id)
    except Exception:
        logger.warning("Failed to read user=%s", user_id, exc_info=True)
        return None


def is_billing_allowed(user_id: str) -> bool:
    """Check the Cosmos user record for operator / billing-allowed status."""
    doc = get_user(user_id)
    return bool(doc and doc.get("billing_allowed"))


def set_user_role(
    user_id: str,
    *,
    billing_allowed: bool | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """Set operator flags on a user record. Returns the updated document."""
    from treesight.storage.cosmos import cosmos_available, read_item, upsert_item

    if not cosmos_available():
        raise RuntimeError("Cosmos DB is not available")

    existing: dict[str, Any] = read_item("users", user_id, user_id) or {
        "id": user_id,
        "user_id": user_id,
        "first_seen": datetime.now(UTC).isoformat(),
    }

    existing["last_modified"] = datetime.now(UTC).isoformat()

    if billing_allowed is not None:
        existing["billing_allowed"] = billing_allowed

    if tier is not None:
        from treesight.security.billing import normalize_tier, save_subscription

        normalized = normalize_tier(tier)
        save_subscription(user_id, {"tier": normalized, "status": "active"})
        existing["assigned_tier"] = normalized

    from treesight.models.records import UserRecord

    UserRecord.model_validate(existing)
    latest = read_item("users", user_id, user_id)
    _preserve_quota_fields(existing, latest)
    upsert_item("users", existing)
    return existing


def lookup_user_by_email(email: str) -> dict[str, Any] | None:
    """Find a user by email address (case-insensitive)."""
    from treesight.storage.cosmos import cosmos_available, query_items

    if not cosmos_available() or not email:
        return None

    try:
        results = query_items(
            "users",
            "SELECT * FROM c WHERE LOWER(c.email) = LOWER(@email)",
            parameters=[{"name": "@email", "value": email.strip()}],
        )
        if not results:
            return None

        def _user_record_priority_key(doc: dict[str, Any]) -> tuple[int, int, int, str]:
            # Prefer records likely to carry entitlement/quota state first:
            # billing_allowed > quota used > org membership > newest last_seen
            # (ISO 8601 lexical ordering).
            quota = doc.get("quota")
            used = 0
            if isinstance(quota, dict):
                try:
                    used = int(quota.get("used", 0))
                except (TypeError, ValueError):
                    used = 0
            return (
                1 if doc.get("billing_allowed") else 0,
                1 if used > 0 else 0,
                1 if doc.get("org_id") else 0,
                str(doc.get("last_seen", "")),
            )

        return max(results, key=_user_record_priority_key)
    except Exception:
        logger.warning("Email lookup failed for email=%s", email, exc_info=True)
        return None


def list_users(*, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent users ordered by last_seen."""
    from treesight.storage.cosmos import cosmos_available, query_items

    if not cosmos_available():
        return []

    try:
        return query_items(
            "users",
            "SELECT c.id, c.user_id, c.email, c.display_name,"
            " c.identity_provider, c.billing_allowed, c.assigned_tier,"
            " c.first_seen, c.last_seen"
            " FROM c ORDER BY c.last_seen DESC OFFSET 0 LIMIT @limit",
            parameters=[{"name": "@limit", "value": min(limit, 200)}],
        )
    except Exception:
        logger.warning("User list query failed", exc_info=True)
        return []


def update_user_profile(user_id: str, *, display_name: str) -> dict[str, Any]:
    """Update a user's profile (e.g., display name).

    Raises ValueError if user not found or display_name invalid.
    """
    from treesight.storage.cosmos import cosmos_available, read_item, upsert_item

    if not cosmos_available():
        raise RuntimeError("Cosmos DB is not available")

    if not display_name or not display_name.strip():
        raise ValueError("display_name must not be empty")

    if len(display_name) > 200:
        raise ValueError("display_name must be ≤200 characters")

    existing = read_item("users", user_id, user_id)
    if not existing:
        raise ValueError(f"User {user_id} not found")

    from treesight.models.records import UserRecord

    existing["display_name"] = display_name.strip()
    existing["last_modified"] = datetime.now(UTC).isoformat()

    UserRecord.model_validate(existing)
    latest = read_item("users", user_id, user_id)
    _preserve_quota_fields(existing, latest)
    upsert_item("users", existing)
    logger.info("Profile updated user=%s", user_id)
    return existing


def delete_user(user_id: str, *, transfer_to_user_id: str | None = None) -> None:
    """Delete a user account with cascade cleanup.

    - Removes user from all orgs
    - If user is sole owner of an org, must transfer to another member
    - Deletes all user data (runs, analysis, etc.)
    - Removes the user document

    Raises ValueError if sole owner without transfer target or transfer target
    is not a member of the org.
    """
    from treesight.security.orgs import (
        change_member_role,
        get_org,
        list_orgs_for_user,
        remove_member,
    )
    from treesight.storage.cosmos import cosmos_available, delete_item, query_items

    if not cosmos_available():
        raise RuntimeError("Cosmos DB is not available")

    # Get all orgs the user is a member of
    user_orgs = list_orgs_for_user(user_id)

    # Handle org membership: remove from orgs, transfer ownership if needed
    for user_org in user_orgs:
        org_id = user_org.get("org_id")
        if not isinstance(org_id, str) or not org_id:
            logger.warning("Skipping org entry with missing org_id for user %s", user_id)
            continue
        org_role = user_org.get("org_role")

        if org_role == "owner":
            # Check if sole owner
            org = get_org(org_id)
            if not org:
                logger.warning("Org %s not found during delete_user", org_id)
                continue

            owners = [m for m in org.get("members", []) if m["role"] == "owner"]
            if len(owners) == 1:
                # User is sole owner — must transfer
                if not transfer_to_user_id:
                    raise ValueError(
                        f"User {user_id} is sole owner of org {org_id}; "
                        "must specify transfer_to_user_id to delete account"
                    )

                # Verify transfer target is a member
                target_member = next(
                    (m for m in org.get("members", []) if m["user_id"] == transfer_to_user_id),
                    None,
                )
                if not target_member:
                    raise ValueError(f"User {transfer_to_user_id} is not a member of org {org_id}")

                # Promote transfer target to owner
                change_member_role(org_id, transfer_to_user_id, "owner")
                logger.info(
                    "Ownership transferred org=%s from=%s to=%s",
                    org_id,
                    user_id,
                    transfer_to_user_id,
                )

        # Remove user from org
        remove_member(org_id, user_id)

    # Cascade delete user data (runs, analysis, etc.)
    try:
        runs = query_items(
            "user_runs",
            "SELECT c.id FROM c WHERE c.user_id = @user_id",
            parameters=[{"name": "@user_id", "value": user_id}],
        )
        for run in runs:
            try:
                delete_item("user_runs", run["id"], user_id)
            except Exception:
                logger.warning(
                    "Failed to delete run during user deletion user=%s run=%s",
                    user_id,
                    run["id"],
                    exc_info=True,
                )
    except Exception:
        logger.warning("Failed to query user runs during deletion user=%s", user_id, exc_info=True)

    # Delete user document
    delete_item("users", user_id, user_id)
    logger.info("User deleted user=%s", user_id)

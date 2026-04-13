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
        existing["last_seen"] = now

        if email:
            existing["email"] = email
        if display_name:
            existing["display_name"] = display_name
        if identity_provider:
            existing["identity_provider"] = identity_provider

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
        return results[0] if results else None
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

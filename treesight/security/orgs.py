"""Organisation management service (#614).

CRUD operations for orgs, members, and invites.  All documents live in
the Cosmos ``orgs`` container (partition key ``/org_id``).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Invite validity window
INVITE_TTL_DAYS = 7


# ── Org CRUD ──────────────────────────────────────────────────


def create_org(
    user_id: str,
    *,
    name: str = "My Organisation",
    email: str = "",
) -> dict[str, Any]:
    """Create a new organisation with *user_id* as the initial owner."""
    from treesight.storage.cosmos import upsert_item

    org_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    doc: dict[str, Any] = {
        "id": org_id,
        "org_id": org_id,
        "doc_type": "org",
        "name": name,
        "created_by": user_id,
        "created_at": now,
        "members": [
            {
                "user_id": user_id,
                "email": email,
                "role": "owner",
                "joined_at": now,
            }
        ],
        "billing": {},
    }

    upsert_item("orgs", doc)
    _set_user_org(user_id, org_id, "owner")
    logger.info("Org created org_id=%s by user=%s", org_id, user_id)
    return doc


def get_org(org_id: str) -> dict[str, Any] | None:
    """Return the org document, or None."""
    from treesight.storage.cosmos import read_item

    return read_item("orgs", org_id, org_id)


def update_org_name(org_id: str, name: str) -> dict[str, Any]:
    """Update the org display name."""
    from treesight.storage.cosmos import upsert_item

    org = get_org(org_id)
    if not org:
        raise ValueError(f"Org {org_id} not found")
    org["name"] = name[:200]
    upsert_item("orgs", org)
    return org


def get_user_org(user_id: str) -> dict[str, Any] | None:
    """Return the org the user belongs to, or None."""
    from treesight.security.users import get_user

    user = get_user(user_id)
    if not user or not user.get("org_id"):
        return None
    return get_org(user["org_id"])


# ── Member management ────────────────────────────────────────


def add_member(
    org_id: str,
    user_id: str,
    *,
    email: str = "",
    role: str = "member",
) -> dict[str, Any]:
    """Add a member to an org."""
    from treesight.storage.cosmos import upsert_item

    org = get_org(org_id)
    if not org:
        raise ValueError(f"Org {org_id} not found")

    members = org.get("members", [])
    if any(m["user_id"] == user_id for m in members):
        raise ValueError(f"User {user_id} is already a member")

    members.append(
        {
            "user_id": user_id,
            "email": email,
            "role": role,
            "joined_at": datetime.now(UTC).isoformat(),
        }
    )
    org["members"] = members
    upsert_item("orgs", org)
    _set_user_org(user_id, org_id, role)
    return org


def remove_member(org_id: str, user_id: str) -> dict[str, Any]:
    """Remove a member from an org.  Cannot remove the last owner."""
    from treesight.storage.cosmos import upsert_item

    org = get_org(org_id)
    if not org:
        raise ValueError(f"Org {org_id} not found")

    members = org.get("members", [])
    target = next((m for m in members if m["user_id"] == user_id), None)
    if not target:
        raise ValueError(f"User {user_id} is not a member")

    if target["role"] == "owner":
        owners = [m for m in members if m["role"] == "owner"]
        if len(owners) <= 1:
            raise ValueError("Cannot remove the last owner — transfer ownership first")

    org["members"] = [m for m in members if m["user_id"] != user_id]
    upsert_item("orgs", org)
    _clear_user_org(user_id)
    return org


def change_member_role(org_id: str, user_id: str, new_role: str) -> dict[str, Any]:
    """Change a member's role.  Blocked if demoting the last owner."""
    from treesight.storage.cosmos import upsert_item

    if new_role not in ("owner", "member"):
        raise ValueError(f"Invalid role: {new_role}")

    org = get_org(org_id)
    if not org:
        raise ValueError(f"Org {org_id} not found")

    members = org.get("members", [])
    target = next((m for m in members if m["user_id"] == user_id), None)
    if not target:
        raise ValueError(f"User {user_id} is not a member")

    if target["role"] == "owner" and new_role == "member":
        owners = [m for m in members if m["role"] == "owner"]
        if len(owners) <= 1:
            raise ValueError("Cannot demote the last owner — promote someone else first")

    target["role"] = new_role
    upsert_item("orgs", org)
    _set_user_org(user_id, org_id, new_role)
    return org


def list_members(org_id: str) -> list[dict[str, Any]]:
    """Return the member list for an org."""
    org = get_org(org_id)
    if not org:
        return []
    return org.get("members", [])


# ── Invites ──────────────────────────────────────────────────


def create_invite(org_id: str, email: str, *, invited_by: str) -> dict[str, Any]:
    """Create a pending invite.  Idempotent — overwrites existing invite for same email."""
    from treesight.storage.cosmos import upsert_item

    now = datetime.now(UTC)
    invite_id = f"invite:{org_id}:{email.lower().strip()}"

    doc: dict[str, Any] = {
        "id": invite_id,
        "org_id": org_id,
        "doc_type": "invite",
        "email": email.lower().strip(),
        "invited_by": invited_by,
        "invited_at": now.isoformat(),
        "expires_at": (now + timedelta(days=INVITE_TTL_DAYS)).isoformat(),
    }

    upsert_item("orgs", doc)
    logger.info("Invite created org=%s email=%s", org_id, email)
    return doc


def check_pending_invite(email: str) -> dict[str, Any] | None:
    """Find a non-expired invite for *email*."""
    from treesight.storage.cosmos import query_items

    now = datetime.now(UTC).isoformat()
    results = query_items(
        "orgs",
        "SELECT * FROM c WHERE c.doc_type = 'invite'"
        " AND LOWER(c.email) = LOWER(@email)"
        " AND c.expires_at > @now",
        parameters=[
            {"name": "@email", "value": email.lower().strip()},
            {"name": "@now", "value": now},
        ],
    )
    return results[0] if results else None


def accept_invite(invite: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Accept a pending invite — add user to org and delete the invite."""
    from treesight.storage.cosmos import delete_item

    org = add_member(
        invite["org_id"],
        user_id,
        email=invite["email"],
        role="member",
    )

    delete_item("orgs", invite["id"], invite["org_id"])
    logger.info(
        "Invite accepted org=%s user=%s email=%s",
        invite["org_id"],
        user_id,
        invite["email"],
    )
    return org


# ── Helpers ──────────────────────────────────────────────────


def _set_user_org(user_id: str, org_id: str, role: str) -> None:
    """Update the user document with org association."""
    from treesight.storage.cosmos import cosmos_available, read_item, upsert_item

    if not cosmos_available():
        return
    try:
        existing = read_item("users", user_id, user_id) or {
            "id": user_id,
            "user_id": user_id,
        }
        existing["org_id"] = org_id
        existing["org_role"] = role
        upsert_item("users", existing)
    except Exception:
        logger.warning("Failed to set org on user=%s", user_id, exc_info=True)


def _clear_user_org(user_id: str) -> None:
    """Remove org association from user document."""
    from treesight.storage.cosmos import cosmos_available, read_item, upsert_item

    if not cosmos_available():
        return
    try:
        existing = read_item("users", user_id, user_id)
        if existing:
            existing.pop("org_id", None)
            existing.pop("org_role", None)
            upsert_item("users", existing)
    except Exception:
        logger.warning("Failed to clear org on user=%s", user_id, exc_info=True)

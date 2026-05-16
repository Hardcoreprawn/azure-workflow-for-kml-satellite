"""Organisation management endpoints (#614).

Provides CRUD for orgs, member management, and invite handling.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
Azure Functions worker cannot resolve deferred type annotations at
function-index time.
"""

import json
import logging
from typing import Any

import azure.functions as func

from blueprints._helpers import cors_headers, error_response, require_auth

logger = logging.getLogger(__name__)

bp = func.Blueprint()


def _require_org_owner(
    user_id: str, org_id: str
) -> tuple[dict[str, Any] | None, func.HttpResponse | None]:
    """Return (org, None) if user is an owner, or (None, error_response)."""
    from treesight.security.orgs import get_org

    org = get_org(org_id)
    if not org:
        return None, None  # will be handled by caller
    members = org.get("members", [])
    me = next((m for m in members if m["user_id"] == user_id), None)
    if not me or me.get("role") != "owner":
        return None, None
    return org, None


# ── GET/POST /api/org ────────────────────────────────────────


@bp.route(
    route="org",
    methods=["GET", "POST", "PATCH", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def org_endpoint(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Org CRUD: GET (my org), POST (create), PATCH (rename)."""
    del auth_claims  # unused
    if req.method == "GET":
        return _get_org(req, user_id)
    if req.method == "POST":
        return _create_org(req, user_id)
    if req.method == "PATCH":
        return _update_org(req, user_id)
    return error_response(405, "Method not allowed", req=req)


def _get_org(req: func.HttpRequest, user_id: str) -> func.HttpResponse:
    from treesight.security.orgs import get_user_org

    org = get_user_org(user_id)
    if not org:
        return func.HttpResponse(
            json.dumps({"org": None}),
            status_code=200,
            headers={**cors_headers(req), "Content-Type": "application/json"},
        )
    safe = {k: v for k, v in org.items() if not k.startswith("_")}
    return func.HttpResponse(
        json.dumps({"org": safe}),
        status_code=200,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


def _create_org(req: func.HttpRequest, user_id: str) -> func.HttpResponse:
    from treesight.security.orgs import create_org, get_user_org
    from treesight.security.users import get_user

    # Check user doesn't already have an org
    existing = get_user_org(user_id)
    if existing:
        return error_response(409, "You already belong to an organisation", req=req)

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    name = body.get("name", "My Organisation") if isinstance(body, dict) else "My Organisation"
    user = get_user(user_id)
    email = user.get("email", "") if user else ""

    org = create_org(user_id, name=str(name)[:200], email=email)
    safe = {k: v for k, v in org.items() if not k.startswith("_")}
    return func.HttpResponse(
        json.dumps({"org": safe}),
        status_code=201,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


def _update_org(req: func.HttpRequest, user_id: str) -> func.HttpResponse:
    from treesight.security.orgs import get_user_org, update_org_name
    from treesight.security.users import get_user

    user = get_user(user_id)
    org_id = user.get("org_id") if user else None
    if not org_id:
        return error_response(404, "You do not belong to an organisation", req=req)

    # Owner check
    org = get_user_org(user_id)
    if not org:
        return error_response(404, "Organisation not found", req=req)
    members = org.get("members", [])
    me = next((m for m in members if m["user_id"] == user_id), None)
    if not me or me.get("role") != "owner":
        return error_response(403, "Only owners can rename the organisation", req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON", req=req)

    name = body.get("name") if isinstance(body, dict) else None
    if not name or not isinstance(name, str):
        return error_response(400, "name is required", req=req)

    updated = update_org_name(org_id, name)
    safe = {k: v for k, v in updated.items() if not k.startswith("_")}
    return func.HttpResponse(
        json.dumps({"org": safe}),
        status_code=200,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


# ── POST /api/org/invite ────────────────────────────────────


@bp.route(route="org/invite", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def org_invite(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """POST /api/org/invite — owner invites a member by email."""
    del auth_claims  # unused
    from treesight.security.orgs import create_invite, get_user_org
    from treesight.security.users import get_user

    user = get_user(user_id)
    if not user:
        return error_response(404, "User not found", req=req)
    org_id = user.get("org_id")
    if not org_id:
        return error_response(404, "You do not belong to an organisation", req=req)

    # Read ownership from the org document — user doc org_role can be stale.
    org = get_user_org(user_id)
    if not org:
        return error_response(404, "Organisation not found", req=req)
    _members = org.get("members", [])
    _me = next((m for m in _members if m["user_id"] == user_id), None)
    if not _me or _me.get("role") != "owner":
        return error_response(403, "Only owners can invite members", req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON", req=req)

    email = body.get("email") if isinstance(body, dict) else None
    if not email or not isinstance(email, str) or "@" not in email:
        return error_response(400, "Valid email is required", req=req)

    invite = create_invite(org_id, email, invited_by=user_id)
    safe = {k: v for k, v in invite.items() if not k.startswith("_")}
    return func.HttpResponse(
        json.dumps({"invite": safe}),
        status_code=201,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


# ── GET /api/org/members ────────────────────────────────────


@bp.route(route="org/members", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def org_members_list(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """GET /api/org/members — list org members."""
    del auth_claims  # unused
    from treesight.security.orgs import list_members
    from treesight.security.users import get_user

    user = get_user(user_id)
    org_id = user.get("org_id") if user else None
    if not org_id:
        return error_response(404, "You do not belong to an organisation", req=req)

    members = list_members(org_id)
    return func.HttpResponse(
        json.dumps({"members": members}),
        status_code=200,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


# ── DELETE/PATCH /api/org/members/{user_id} ──────────────────


@bp.route(
    route="org/members/{member_id}",
    methods=["DELETE", "PATCH", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def org_member_manage(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """DELETE (remove) or PATCH (change role) a member."""
    del auth_claims  # unused
    member_id = req.route_params.get("member_id", "")
    if not member_id:
        return error_response(400, "member_id is required", req=req)

    from treesight.security.users import get_user

    user = get_user(user_id)
    if not user:
        return error_response(404, "You do not belong to an organisation", req=req)
    org_id = user.get("org_id")
    if not org_id:
        return error_response(404, "You do not belong to an organisation", req=req)
    # Read ownership from the org document — user doc org_role can be stale.
    from treesight.security.orgs import get_org

    _org = get_org(org_id)
    if not _org:
        return error_response(404, "Organisation not found", req=req)
    _members = _org.get("members", [])
    _me = next((m for m in _members if m["user_id"] == user_id), None)
    if not _me or _me.get("role") != "owner":
        return error_response(403, "Only owners can manage members", req=req)

    if req.method == "DELETE":
        return _remove_member(req, org_id, member_id)
    if req.method == "PATCH":
        return _change_role(req, org_id, member_id)
    return error_response(405, "Method not allowed", req=req)


def _remove_member(req: func.HttpRequest, org_id: str, member_id: str) -> func.HttpResponse:
    from treesight.security.orgs import remove_member

    try:
        remove_member(org_id, member_id)
    except ValueError as exc:
        return error_response(400, str(exc), req=req)

    return func.HttpResponse(
        json.dumps({"removed": member_id}),
        status_code=200,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


def _change_role(req: func.HttpRequest, org_id: str, member_id: str) -> func.HttpResponse:
    from treesight.security.orgs import change_member_role

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON", req=req)

    role = body.get("role") if isinstance(body, dict) else None
    if role not in ("owner", "member"):
        return error_response(400, "role must be 'owner' or 'member'", req=req)

    try:
        org = change_member_role(org_id, member_id, role)
    except ValueError as exc:
        return error_response(400, str(exc), req=req)

    safe = {k: v for k, v in org.items() if not k.startswith("_")}
    return func.HttpResponse(
        json.dumps({"org": safe}),
        status_code=200,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


# ── GET /api/org/invites ────────────────────────────────────


@bp.route(route="org/invites", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth
def org_invites_list(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """GET /api/org/invites — list pending invitations for the org."""
    del auth_claims  # unused
    from treesight.security.orgs import list_pending_invites
    from treesight.security.users import get_user

    user = get_user(user_id)
    org_id = user.get("org_id") if user else None
    if not org_id:
        return error_response(404, "You do not belong to an organisation", req=req)

    invites = list_pending_invites(org_id)
    # Filter sensitive fields; exclude token — live JWTs must not be exposed in listings.
    safe_invites = [
        {k: v for k, v in inv.items() if not k.startswith("_") and k != "token"}
        for inv in invites
    ]
    return func.HttpResponse(
        json.dumps({"invites": safe_invites}),
        status_code=200,
        headers={**cors_headers(req), "Content-Type": "application/json"},
    )


# ── PATCH /api/org/invites/{email}/revoke ──────────────────


@bp.route(
    route="org/invites/{email}/revoke",
    methods=["PATCH", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def org_invite_revoke(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """PATCH /api/org/invites/{email}/revoke — revoke a pending invitation."""
    del auth_claims  # unused
    email = req.route_params.get("email", "")
    if not email:
        return error_response(400, "email is required", req=req)

    from treesight.security.orgs import revoke_invite
    from treesight.security.users import get_user

    user = get_user(user_id)
    org_id = user.get("org_id") if user else None
    if not org_id:
        return error_response(404, "You do not belong to an organisation", req=req)

    # Read ownership from the org document — user doc org_role can be stale.
    from treesight.security.orgs import get_org

    _org = get_org(org_id)
    if not _org:
        return error_response(404, "Organisation not found", req=req)
    _members = _org.get("members", [])
    _me = next((m for m in _members if m["user_id"] == user_id), None)
    if not _me or _me.get("role") != "owner":
        return error_response(403, "Only owners can revoke invitations", req=req)

    try:
        invite_doc = revoke_invite(org_id, email)
        safe = {k: v for k, v in invite_doc.items() if not k.startswith("_")}
        return func.HttpResponse(
            json.dumps({"invite": safe}),  # N1 fix: was "org"
            status_code=200,
            headers={**cors_headers(req), "Content-Type": "application/json"},
        )
    except ValueError as exc:
        return error_response(400, str(exc), req=req)


# ── POST /api/org/invites/{token}/accept ───────────────────


@bp.route(
    route="org/invites/{token}/accept",
    methods=["POST", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def org_invite_accept(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """POST /api/org/invites/{token}/accept — accept an invitation by token."""
    del auth_claims  # unused
    token = req.route_params.get("token", "")
    if not token:
        return error_response(400, "token is required", req=req)

    from treesight.security.orgs import accept_invite_by_token

    try:
        org = accept_invite_by_token(token, user_id)
        safe = {k: v for k, v in org.items() if not k.startswith("_")}
        return func.HttpResponse(
            json.dumps({"org": safe}),
            status_code=200,
            headers={**cors_headers(req), "Content-Type": "application/json"},
        )
    except ValueError as exc:
        return error_response(400, str(exc), req=req)

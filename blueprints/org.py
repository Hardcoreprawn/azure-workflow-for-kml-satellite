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

from blueprints._helpers import check_auth, cors_headers, cors_preflight, error_response

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
def org_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Org CRUD: GET (my org), POST (create), PATCH (rename)."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

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
def org_invite(req: func.HttpRequest) -> func.HttpResponse:
    """POST /api/org/invite — owner invites a member by email."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

    from treesight.security.orgs import create_invite
    from treesight.security.users import get_user

    user = get_user(user_id)
    if not user:
        return error_response(404, "You do not belong to an organisation", req=req)
    org_id = user.get("org_id")
    if not org_id:
        return error_response(404, "You do not belong to an organisation", req=req)

    org_role = user.get("org_role")
    if org_role != "owner":
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
def org_members_list(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/org/members — list org members."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

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
def org_member_manage(req: func.HttpRequest) -> func.HttpResponse:
    """DELETE (remove) or PATCH (change role) a member."""
    if req.method == "OPTIONS":
        return cors_preflight(req)

    try:
        _claims, user_id = check_auth(req)
    except ValueError as exc:
        return error_response(401, str(exc), req=req)

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
    if user.get("org_role") != "owner":
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

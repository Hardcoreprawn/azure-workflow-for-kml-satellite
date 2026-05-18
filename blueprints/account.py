"""Account & user profile endpoints (#830).

Provides user profile management and GDPR-compliant account deletion.

NOTE: Do NOT add ``from __future__ import annotations`` to this module.
Azure Functions worker cannot resolve deferred type annotations at
function-index time.
"""

import json
import logging

import azure.functions as func

from blueprints._helpers import cors_headers, error_response, require_auth

logger = logging.getLogger(__name__)

bp = func.Blueprint()


# ── GET /api/user ────────────────────────────────────


@bp.route(
    route="user",
    methods=["GET", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def get_profile_endpoint(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """Get current user profile."""
    del auth_claims  # unused

    try:
        from treesight.security.users import get_user

        user = get_user(user_id)
        if not user:
            return error_response(404, "User not found", req=req)
        safe_user = {k: v for k, v in user.items() if not k.startswith("_")}
        return func.HttpResponse(
            json.dumps(safe_user),
            status_code=200,
            headers={**cors_headers(req), "Content-Type": "application/json"},
        )
    except RuntimeError as e:
        if "not available" in str(e).lower():
            return error_response(503, "Cosmos DB is not available", req=req)
        logger.error("Unexpected error fetching profile: %s", e, exc_info=True)
        return error_response(500, "Internal server error", req=req)
    except Exception as e:
        logger.error("Unexpected error fetching profile: %s", e, exc_info=True)
        return error_response(500, "Internal server error", req=req)


# ── PATCH /api/user/profile ──────────────────────────────────


@bp.route(
    route="user/profile",
    methods=["PATCH", "OPTIONS"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def update_profile_endpoint(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """Update user profile (display name)."""
    del auth_claims  # unused

    if req.method != "PATCH":
        return error_response(405, "Method not allowed", req=req)

    try:
        body = req.get_json()
    except ValueError:
        return error_response(400, "Invalid JSON", req=req)

    if not isinstance(body, dict):
        return error_response(400, "Expected JSON object", req=req)

    display_name = body.get("display_name", "").strip()
    if not display_name:
        return error_response(400, "display_name is required and must not be empty", req=req)

    try:
        from treesight.security.users import update_user_profile

        user = update_user_profile(user_id, display_name=display_name)
        safe_user = {k: v for k, v in user.items() if not k.startswith("_")}
        return func.HttpResponse(
            json.dumps({"user": safe_user}),
            status_code=200,
            headers={**cors_headers(req), "Content-Type": "application/json"},
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            return error_response(404, str(e), req=req)
        return error_response(400, str(e), req=req)
    except RuntimeError as e:
        if "not available" in str(e).lower():
            return error_response(503, "Cosmos DB is not available", req=req)
        logger.error("Unexpected error updating profile: %s", e, exc_info=True)
        return error_response(500, "Internal server error", req=req)
    except Exception as e:
        logger.error("Unexpected error updating profile: %s", e, exc_info=True)
        return error_response(500, "Internal server error", req=req)


# ── DELETE /api/user ──────────────────────────────────────────


@bp.route(
    route="user",
    methods=["DELETE"],
    auth_level=func.AuthLevel.ANONYMOUS,
)
@require_auth
def delete_account_endpoint(
    req: func.HttpRequest, *, auth_claims: dict, user_id: str
) -> func.HttpResponse:
    """Delete user account (GDPR-compliant cascading deletion).

    Query parameters:
    - transfer_to: user_id to transfer org ownership to (required if user is sole owner)
    """
    del auth_claims  # unused

    if req.method != "DELETE":
        return error_response(405, "Method not allowed", req=req)

    # Extract transfer_to parameter
    transfer_to = req.params.get("transfer_to", "").strip() or None

    try:
        from treesight.security.users import delete_user

        delete_user(user_id, transfer_to_user_id=transfer_to)
        return func.HttpResponse(
            b"",
            status_code=204,
            headers=cors_headers(req),
        )
    except ValueError as e:
        return error_response(400, str(e), req=req)
    except RuntimeError as e:
        if "not available" in str(e).lower():
            return error_response(503, "Cosmos DB is not available", req=req)
        logger.error("Unexpected error deleting account: %s", e, exc_info=True)
        return error_response(500, "Internal server error", req=req)
    except Exception as e:
        logger.error("Unexpected error deleting account: %s", e, exc_info=True)
        return error_response(500, "Internal server error", req=req)

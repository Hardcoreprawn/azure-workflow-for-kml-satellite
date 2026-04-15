"""Auth session blueprint — issues HMAC session tokens (#534)."""

import json
import logging

import azure.functions as func

from blueprints._helpers import cors_headers, error_response, require_auth_hmac_exempt
from treesight.config import AUTH_HMAC_KEY
from treesight.security.auth import sign_session_token

logger = logging.getLogger(__name__)

bp = func.Blueprint()


@bp.function_name("auth_session")
@bp.route(route="auth/session", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
@require_auth_hmac_exempt
def auth_session(req: func.HttpRequest, *, auth_claims: dict, user_id: str) -> func.HttpResponse:
    """Issue an HMAC-signed session token for the authenticated user.

    The frontend calls this after obtaining the client principal from
    ``/.auth/me`` and sends the returned token as ``X-Auth-Session``
    on subsequent API requests.
    """
    if not AUTH_HMAC_KEY:
        return func.HttpResponse(
            json.dumps({"token": "", "expires_at": 0, "hmac_enabled": False}),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers(req),
        )

    if user_id == "anonymous":
        return error_response(401, "Authentication required for session token", req=req)

    result = sign_session_token(user_id, key=AUTH_HMAC_KEY)
    logger.info("Session token issued for user %s", user_id[:8])
    return func.HttpResponse(
        json.dumps({**result, "hmac_enabled": True}),
        status_code=200,
        mimetype="application/json",
        headers=cors_headers(req),
    )

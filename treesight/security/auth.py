"""SWA built-in auth: parse X-MS-CLIENT-PRINCIPAL header.

Azure Static Web Apps validates the OAuth session server-side and injects
a Base64-encoded JSON header into every /api/* request.  This module
decodes that header and extracts user identity — no JWT validation, JWKS
fetching, or client secrets needed.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def auth_enabled() -> bool:
    """Return True — SWA built-in auth is always available.

    When ``REQUIRE_AUTH`` is set the function still returns True, but callers
    treat missing headers as a 401 rather than falling through to anonymous.
    """
    return True


def parse_client_principal(header_value: str) -> dict[str, Any]:
    """Decode the ``X-MS-CLIENT-PRINCIPAL`` header and return the principal dict.

    Raises ``ValueError`` with a user-safe message on any decoding failure.
    """
    if not header_value:
        raise ValueError("Missing X-MS-CLIENT-PRINCIPAL header")

    try:
        decoded = base64.b64decode(header_value)
        principal = json.loads(decoded)
    except Exception:
        raise ValueError("Malformed X-MS-CLIENT-PRINCIPAL header") from None

    if not isinstance(principal, dict) or not principal.get("userId"):
        raise ValueError("X-MS-CLIENT-PRINCIPAL missing userId")

    return principal


def get_user_id(principal: dict[str, Any]) -> str:
    """Extract the user identifier from a decoded client principal."""
    return principal.get("userId", "")

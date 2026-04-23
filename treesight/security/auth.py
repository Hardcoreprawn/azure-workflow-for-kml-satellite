"""SWA built-in auth: parse X-MS-CLIENT-PRINCIPAL header.

Azure Static Web Apps validates the OAuth session server-side and injects
a Base64-encoded JSON header into every /api/* request.  This module
decodes that header and extracts user identity — no JWT validation, JWKS
fetching, or client secrets needed.

When ``AUTH_HMAC_KEY`` is configured the module also provides HMAC-SHA256
signing and verification so callers can reject forged principal headers
(see #534).
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import logging
import time
from functools import lru_cache
from typing import Any

import requests

from treesight.config import (
    AUTH_MODE,
    CIAM_API_AUDIENCE,
    CIAM_AUTHORITY,
    CIAM_JWT_LEEWAY_SECONDS,
    CIAM_TENANT_ID,
)

logger = logging.getLogger(__name__)

# Session token lifetime (seconds).  Tokens issued by /api/auth/session
# are valid for this duration before the client must re-issue.
SESSION_TOKEN_TTL = 3600  # 1 hour


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
        decoded = base64.b64decode(header_value, validate=True)
        principal = json.loads(decoded)
    except Exception:
        raise ValueError("Malformed X-MS-CLIENT-PRINCIPAL header") from None

    if not isinstance(principal, dict) or not principal.get("userId"):
        raise ValueError("X-MS-CLIENT-PRINCIPAL missing userId")

    return principal


def get_user_id(principal: dict[str, Any]) -> str:
    """Extract the user identifier from a decoded client principal."""
    return principal.get("userId", "")


def parse_bearer_token(authorization_header: str) -> str | None:
    """Extract a bearer token from ``Authorization`` header value."""
    if not isinstance(authorization_header, str):
        return None
    if not authorization_header:
        return None
    if not authorization_header.startswith("Bearer "):
        return None

    token = authorization_header[7:].strip()
    if not token:
        raise ValueError("Missing bearer token")
    return token


def get_user_id_from_bearer_claims(claims: dict[str, Any]) -> str:
    """Extract stable user id from verified JWT claims."""
    tenant_id = claims.get("tid")
    object_id = claims.get("oid")
    if tenant_id and object_id:
        return f"{tenant_id}:{object_id}"
    return ""


def verify_bearer_token(token: str) -> dict[str, Any]:
    """Verify CIAM bearer JWT and return decoded claims.

    Verification is enabled only in ``AUTH_MODE`` dual or bearer_only.
    """
    if AUTH_MODE not in {"dual", "bearer_only"}:
        raise ValueError("Bearer token auth is not enabled")
    if not CIAM_AUTHORITY or not CIAM_TENANT_ID or not CIAM_API_AUDIENCE:
        raise ValueError("Bearer token auth is not configured")

    try:
        import jwt
    except Exception as exc:  # pragma: no cover - dependency wiring failure
        raise ValueError("Bearer token verification dependency is unavailable") from exc

    try:
        metadata = _oidc_metadata(CIAM_AUTHORITY, CIAM_TENANT_ID)
        signing_key = _jwks_client(metadata["jwks_uri"]).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key=signing_key,
            algorithms=["RS256"],
            audience=CIAM_API_AUDIENCE,
            issuer=metadata["issuer"],
            leeway=CIAM_JWT_LEEWAY_SECONDS,
            options={
                "require": ["exp", "iss", "aud", "nbf", "tid", "oid", "ver"],
            },
        )
    except Exception:
        raise ValueError("Invalid bearer token") from None

    if claims.get("ver") not in {"1.0", "2.0"}:
        raise ValueError("Invalid bearer token")

    if not get_user_id_from_bearer_claims(claims):
        raise ValueError("Bearer token missing subject")

    return claims


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str):
    """Return a cached PyJWKClient for the given JWKS URL."""
    from jwt import PyJWKClient

    return PyJWKClient(jwks_url)


@lru_cache(maxsize=2)
def _oidc_metadata(authority: str, tenant_id: str) -> dict[str, str]:
    """Fetch OIDC metadata and return issuer/JWKS values."""
    authority = authority.rstrip("/")
    url = f"{authority}/{tenant_id}/v2.0/.well-known/openid-configuration"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    metadata = response.json()

    issuer = metadata.get("issuer")
    jwks_uri = metadata.get("jwks_uri")
    if not issuer or not jwks_uri:
        raise ValueError("Invalid OIDC metadata")

    return {
        "issuer": issuer,
        "jwks_uri": jwks_uri,
    }


# ---------------------------------------------------------------------------
# HMAC-based principal verification (#534)
# ---------------------------------------------------------------------------


def sign_session_token(user_id: str, *, key: str, ttl: int = SESSION_TOKEN_TTL) -> dict[str, Any]:
    """Create an HMAC-signed session token for *user_id*.

    Returns ``{"token": "<base64>.<base64>", "expires_at": <epoch>}``.
    The token embeds the userId and expiry so the backend can verify both
    authenticity and freshness without server-side state.
    """
    expires_at = int(time.time()) + ttl
    payload = json.dumps(
        {"uid": user_id, "exp": expires_at},
        separators=(",", ":"),
    ).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode()
    sig = _hmac.new(key.encode(), payload, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode()
    return {"token": f"{payload_b64}.{sig_b64}", "expires_at": expires_at}


def verify_session_token(token: str, principal_user_id: str, *, key: str) -> None:
    """Verify an HMAC session token matches *principal_user_id*.

    Raises ``ValueError`` with a user-safe message on any failure.
    """
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Malformed session token")

    payload_b64, sig_b64 = parts
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        expected_sig = _hmac.new(key.encode(), payload_bytes, hashlib.sha256).digest()
        actual_sig = base64.urlsafe_b64decode(sig_b64)
    except Exception as exc:
        raise ValueError("Session token decode error") from exc

    if not _hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid session token signature")

    claims = json.loads(payload_bytes)

    if claims.get("exp", 0) < time.time():
        raise ValueError("Session token expired")

    if claims.get("uid") != principal_user_id:
        raise ValueError("Session token userId mismatch")

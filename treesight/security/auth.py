"""Authentication helpers for CIAM bearer JWT verification.

The API auth path is bearer JWT verification (Authorization header) backed
by CIAM OIDC metadata + JWKS signature validation.
"""

from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache
from typing import Any

import requests

from treesight.config import (
    CIAM_API_AUDIENCE,
    CIAM_AUTHORITY,
    CIAM_JWT_LEEWAY_SECONDS,
    CIAM_TENANT_ID,
)

logger = logging.getLogger(__name__)


def auth_enabled() -> bool:
    """Return True to indicate auth helpers are active in this module.

    Runtime request enforcement is handled by API decorators and `REQUIRE_AUTH`.
    """
    return True


def parse_client_principal(header_value: str) -> dict[str, Any]:
    """Decode the X-MS-CLIENT-PRINCIPAL header and return the principal dict."""
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
    header_value = authorization_header.strip()
    if not header_value:
        return None

    parts = header_value.split(None, 1)
    scheme = parts[0]
    if scheme.lower() != "bearer":
        return None

    token = parts[1].strip() if len(parts) > 1 else ""
    if not token:
        raise ValueError("Missing bearer token")
    return token


def get_user_id_from_bearer_claims(claims: dict[str, Any]) -> str:
    """Extract stable user id from verified JWT claims."""
    tenant_id = claims.get("tid")
    object_id = claims.get("oid")
    if tenant_id and object_id:
        return f"{tenant_id}:{object_id}"
    if object_id:
        return str(object_id)
    subject = claims.get("sub")
    if subject:
        return str(subject)
    return ""


def verify_bearer_token(token: str) -> dict[str, Any]:
    """Verify CIAM bearer JWT and return decoded claims."""
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

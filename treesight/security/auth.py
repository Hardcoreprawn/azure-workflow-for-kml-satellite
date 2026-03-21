"""Azure AD B2C JWT validation for API endpoints."""

import logging
import threading
import time
from typing import Any

import jwt
import requests

from treesight.config import B2C_AUDIENCE, B2C_CLIENT_ID, B2C_POLICY_NAME, B2C_TENANT_NAME

logger = logging.getLogger(__name__)

# JWKS cache: thread-safe, refreshes every 24 hours
_jwks_cache: dict[str, Any] = {}
_jwks_lock = threading.Lock()
_JWKS_TTL = 86400  # 24 hours


def _oidc_config_url() -> str:
    """Return the OpenID Connect discovery URL for the B2C policy."""
    return (
        f"https://{B2C_TENANT_NAME}.b2clogin.com/"
        f"{B2C_TENANT_NAME}.onmicrosoft.com/"
        f"{B2C_POLICY_NAME}/v2.0/.well-known/openid-configuration"
    )


def _fetch_jwks() -> dict[str, Any]:
    """Fetch JWKS from B2C discovery endpoint with caching."""
    now = time.monotonic()
    with _jwks_lock:
        if _jwks_cache.get("keys") and now - _jwks_cache.get("fetched_at", 0) < _JWKS_TTL:
            return _jwks_cache["keys"]

    try:
        oidc = requests.get(_oidc_config_url(), timeout=10).json()
        jwks_uri = oidc["jwks_uri"]
        jwks = requests.get(jwks_uri, timeout=10).json()
        with _jwks_lock:
            _jwks_cache["keys"] = jwks
            _jwks_cache["fetched_at"] = time.monotonic()
            _jwks_cache["issuer"] = oidc.get("issuer", "")
        return jwks
    except Exception:
        logger.warning("Failed to fetch B2C JWKS", exc_info=True)
        # Return stale cache if available
        with _jwks_lock:
            return _jwks_cache.get("keys", {})


def _get_issuer() -> str:
    """Return cached issuer from OIDC discovery."""
    with _jwks_lock:
        return _jwks_cache.get("issuer", "")


def b2c_enabled() -> bool:
    """Return True if B2C configuration is present."""
    return bool(B2C_TENANT_NAME and B2C_CLIENT_ID)


def validate_token(auth_header: str) -> dict[str, Any]:
    """Validate a B2C JWT and return the decoded claims.

    Raises ValueError with a user-safe message on failure.
    """
    if not b2c_enabled():
        raise ValueError("Authentication is not configured")

    if not auth_header or not auth_header.startswith("Bearer "):
        raise ValueError("Missing or malformed Authorization header")

    token = auth_header[7:]  # strip "Bearer "

    jwks = _fetch_jwks()
    if not jwks:
        raise ValueError("Could not retrieve signing keys")

    try:
        unverified = jwt.get_unverified_header(token)
    except jwt.DecodeError:
        raise ValueError("Invalid token format")

    kid = unverified.get("kid")
    if not kid:
        raise ValueError("Token missing key ID")

    # Find the matching key
    public_key = None
    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
            break

    if not public_key:
        # Key not found — maybe keys rotated. Force refresh once.
        _jwks_cache.clear()
        jwks = _fetch_jwks()
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
                break

    if not public_key:
        raise ValueError("Token signed with unknown key")

    audience = B2C_AUDIENCE or B2C_CLIENT_ID
    issuer = _get_issuer()

    decode_opts: dict[str, Any] = {
        "algorithms": ["RS256"],
        "audience": audience,
        "options": {"require": ["exp", "iss", "aud"]},
    }
    if issuer:
        decode_opts["issuer"] = issuer

    try:
        claims = jwt.decode(token, public_key, **decode_opts)
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidAudienceError:
        raise ValueError("Token audience mismatch")
    except jwt.InvalidIssuerError:
        raise ValueError("Token issuer mismatch")
    except jwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid token: {exc}")

    return claims


def get_user_id(claims: dict[str, Any]) -> str:
    """Extract the user identifier (subject) from validated claims."""
    return claims.get("sub", claims.get("oid", ""))

"""Valet token system for secure demo artifact downloads (§4.7, §11.2)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from treesight.config import (
    DEMO_VALET_TOKEN_MAX_USES,
    DEMO_VALET_TOKEN_SECRET,
    DEMO_VALET_TOKEN_TTL_SECONDS,
)

# In-memory replay counter. In production, use distributed storage.
_replay_counts: dict[str, int] = {}


def mint_valet_token(
    submission_id: str,
    submission_blob_name: str,
    artifact_path: str,
    recipient_email: str,
    output_container: str,
    *,
    secret: str | None = None,
    ttl_seconds: int | None = None,
    max_uses: int | None = None,
) -> str:
    """Create a signed valet token for artifact download."""
    secret = secret or DEMO_VALET_TOKEN_SECRET
    if not secret:
        raise ValueError("DEMO_VALET_TOKEN_SECRET is not configured")

    ttl = ttl_seconds if ttl_seconds is not None else DEMO_VALET_TOKEN_TTL_SECONDS
    uses = max_uses if max_uses is not None else DEMO_VALET_TOKEN_MAX_USES

    claims: dict[str, str | int] = {
        "submission_id": submission_id,
        "submission_blob_name": submission_blob_name,
        "artifact_path": artifact_path,
        "recipient_hash": hashlib.sha256(recipient_email.lower().encode()).hexdigest(),
        "exp": int(time.time()) + ttl,
        "nonce": uuid.uuid4().hex,
        "max_uses": uses,
        "output_container": output_container,
    }

    payload_bytes = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")

    return f"{payload_b64}.{sig_b64}"


def verify_valet_token(
    token: str,
    *,
    secret: str | None = None,
) -> dict[str, Any]:
    """Verify and decode a valet token. Returns claims dict.

    Raises ValueError on any verification failure.
    """
    secret = secret or DEMO_VALET_TOKEN_SECRET
    if not secret:
        raise ValueError("DEMO_VALET_TOKEN_SECRET is not configured")

    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Malformed token")

    payload_b64, sig_b64 = parts
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        expected_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        actual_sig = base64.urlsafe_b64decode(sig_b64)
    except Exception as exc:
        raise ValueError("Token decode error") from exc

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Invalid token signature")

    claims = json.loads(payload_bytes)

    if claims.get("exp", 0) < time.time():
        raise ValueError("Token expired")

    nonce = claims.get("nonce", "")
    count = _replay_counts.get(nonce, 0)
    max_uses = claims.get("max_uses", 3)
    if count >= max_uses:
        raise ValueError("Token replay limit exceeded")
    _replay_counts[nonce] = count + 1

    return claims

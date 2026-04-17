"""PII redaction helpers for safe logging."""

from __future__ import annotations

import hashlib


def redact_user_id(user_id: str) -> str:
    """Return a hashed prefix of *user_id* safe for logging.

    Uses a SHA-256 digest so no raw PII leaks into logs while
    remaining deterministic (same input → same output) for
    log correlation.
    """
    digest = hashlib.sha256(user_id.encode()).hexdigest()
    return f"u#{digest[:12]}"

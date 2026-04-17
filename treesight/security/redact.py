"""PII redaction helpers for safe logging."""

from __future__ import annotations


def redact_user_id(user_id: str) -> str:
    """Return a truncated user ID safe for logging (no full PII)."""
    return user_id[:8] + "…" if len(user_id) > 8 else user_id

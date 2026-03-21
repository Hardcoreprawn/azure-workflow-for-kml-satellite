"""Structured logging utilities (§10 of SYSTEM_SPEC)."""

from __future__ import annotations

import logging

logger = logging.getLogger("treesight")


def log_phase(
    phase: str,
    step: str,
    instance_id: str = "",
    blob_name: str = "",
    **extra: object,
) -> str:
    """Build a structured log line and emit it at INFO level."""
    parts = [f"phase={phase} step={step}"]
    if instance_id:
        parts.append(f"instance={instance_id}")
    for k, v in extra.items():
        parts.append(f"{k}={v}")
    if blob_name:
        parts.append(f"blob={blob_name}")
    msg = " | ".join(parts)
    logger.info(msg)
    return msg


def log_error(
    phase: str,
    step: str,
    error: str,
    instance_id: str = "",
    **extra: object,
) -> None:
    """Build a structured log line and emit it at ERROR level."""
    parts = [f"phase={phase} step={step}"]
    if instance_id:
        parts.append(f"instance={instance_id}")
    for k, v in extra.items():
        parts.append(f"{k}={v}")
    parts.append(f"error={error}")
    logger.error(" | ".join(parts))

"""Structured logging utilities (§10 of SYSTEM_SPEC).

Emits JSON-structured log records when the ``JsonFormatter`` is installed,
otherwise falls back to the pipe-delimited format for local development.
Use ``configure_logging()`` at startup to install the JSON formatter.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from typing import Any

# Correlation ID propagated through async call chains.
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")

logger = logging.getLogger("treesight")

# Strip control characters (newlines, tabs, etc.) to prevent log injection.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _sanitise(value: object) -> str:
    """Return a log-safe string with control characters removed."""
    return _CONTROL_CHAR_RE.sub("", str(value))


# Keys whose values may be sensitive when logged in human-readable form.
_SENSITIVE_KEYS = {
    "lat",
    "latitude",
    "lon",
    "lng",
    "longitude",
}


def _redact_value_for_log(key: str, value: object) -> str:
    """Return a log-safe representation of a value for console messages.

    For certain keys (e.g. precise geolocation), avoid logging the exact value
    in the human-readable message to reduce the risk of exposing sensitive data.
    Structured properties still receive the full value via ``custom_properties``.
    """
    key_lower = key.lower()
    if key_lower in _SENSITIVE_KEYS:
        # Coarsen numeric coordinates rather than logging full precision.
        try:
            num = float(value)  # type: ignore[arg-type]
        except Exception:
            # Fallback: do not include the raw value.
            return "<redacted>"
        # Round to 2 decimal places (approx ~1 km at mid-latitudes).
        return _sanitise(round(num, 2))
    return _sanitise(value)


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for App Insights ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        cid = correlation_id.get("")
        if cid:
            payload["correlation_id"] = cid
        # Attach custom properties set by log_phase / log_error.
        props: dict[str, Any] = getattr(record, "custom_properties", {})
        if props:
            payload["properties"] = props
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(*, level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root ``treesight`` logger."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("treesight")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def log_phase(
    phase: str,
    step: str,
    instance_id: str = "",
    blob_name: str = "",
    **extra: object,
) -> str:
    """Build a structured log line and emit it at INFO level."""
    phase, step = _sanitise(phase), _sanitise(step)
    instance_id = _sanitise(instance_id)
    blob_name = _sanitise(blob_name)
    props: dict[str, Any] = {"phase": phase, "step": step}
    if instance_id:
        props["instance_id"] = instance_id
    if blob_name:
        props["blob_name"] = blob_name
    props.update(extra)
    cid = correlation_id.get("")
    if cid:
        props["correlation_id"] = cid
    # Human-readable message for console / backward compat.
    parts = [f"phase={phase} step={step}"]
    if instance_id:
        parts.append(f"instance={instance_id}")
    for k, v in extra.items():
        parts.append(f"{_sanitise(k)}={_redact_value_for_log(k, v)}")
    if blob_name:
        parts.append(f"blob={blob_name}")
    msg = " | ".join(parts)
    logger.info(msg, extra={"custom_properties": props})
    return msg


def log_error(
    phase: str,
    step: str,
    error: str,
    instance_id: str = "",
    **extra: object,
) -> None:
    """Build a structured log line and emit it at ERROR level."""
    phase, step = _sanitise(phase), _sanitise(step)
    error = _sanitise(error)
    instance_id = _sanitise(instance_id)
    props: dict[str, Any] = {"phase": phase, "step": step, "error": error}
    if instance_id:
        props["instance_id"] = instance_id
    props.update(extra)
    cid = correlation_id.get("")
    if cid:
        props["correlation_id"] = cid
    parts = [f"phase={phase} step={step}"]
    if instance_id:
        parts.append(f"instance={instance_id}")
    for k, v in extra.items():
        parts.append(f"{_sanitise(k)}={_redact_value_for_log(k, v)}")
    parts.append(f"error={error}")
    logger.error(" | ".join(parts), extra={"custom_properties": props})


def log_duration(
    phase: str,
    step: str,
    started: float,
    instance_id: str = "",
    **extra: object,
) -> str:
    """Log a phase step with its duration in milliseconds."""
    duration_ms = round((time.monotonic() - started) * 1000)
    return log_phase(phase, step, instance_id=instance_id, duration_ms=duration_ms, **extra)  # type: ignore[arg-type]

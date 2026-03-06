"""Process-local circuit breaker for provider API boundaries.

This module implements a defensive, in-memory circuit breaker to avoid
hammering unstable upstream provider APIs. State is process-local by
intent; each worker instance maintains its own breaker windows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import TYPE_CHECKING

from kml_satellite.core.exceptions import PipelineError

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_OPEN_SECONDS = 300
_MIN_FAILURE_THRESHOLD = 1
_MAX_FAILURE_THRESHOLD = 100
_MIN_OPEN_SECONDS = 5
_MAX_OPEN_SECONDS = 86_400


class CircuitBreakerOpenError(PipelineError):
    """Raised when a circuit is currently open for an operation."""

    default_stage = "provider"
    default_code = "CIRCUIT_BREAKER_OPEN"

    def __init__(self, circuit_key: str, seconds_remaining: int) -> None:
        message = (
            f"Circuit open for {circuit_key}; retry after approximately "
            f"{seconds_remaining} second(s)"
        )
        super().__init__(message, retryable=True)
        self.circuit_key = circuit_key
        self.seconds_remaining = seconds_remaining


@dataclass(slots=True)
class _BreakerState:
    failure_count: int = 0
    opened_until: datetime | None = None


_state_lock = Lock()
_state: dict[str, _BreakerState] = {}


def _parse_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _resolve_failure_threshold(override: int | None) -> int:
    if override is not None:
        return max(_MIN_FAILURE_THRESHOLD, min(_MAX_FAILURE_THRESHOLD, override))
    return _parse_int_env(
        "PROVIDER_CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        DEFAULT_FAILURE_THRESHOLD,
        _MIN_FAILURE_THRESHOLD,
        _MAX_FAILURE_THRESHOLD,
    )


def _resolve_open_seconds(override: int | None) -> int:
    if override is not None:
        return max(_MIN_OPEN_SECONDS, min(_MAX_OPEN_SECONDS, override))
    return _parse_int_env(
        "PROVIDER_CIRCUIT_BREAKER_OPEN_SECONDS",
        DEFAULT_OPEN_SECONDS,
        _MIN_OPEN_SECONDS,
        _MAX_OPEN_SECONDS,
    )


def reset_all_circuit_breakers() -> None:
    """Reset all breaker state. Intended for tests."""
    with _state_lock:
        _state.clear()


def call_with_circuit_breaker[T](
    circuit_key: str,
    operation: Callable[[], T],
    *,
    failure_threshold: int | None = None,
    open_seconds: int | None = None,
    now_utc: datetime | None = None,
) -> T:
    """Execute an operation guarded by an in-memory circuit breaker."""
    now = now_utc or datetime.now(UTC)
    threshold = _resolve_failure_threshold(failure_threshold)
    open_duration = _resolve_open_seconds(open_seconds)

    with _state_lock:
        state = _state.setdefault(circuit_key, _BreakerState())
        if state.opened_until is not None and state.opened_until > now:
            remaining = int((state.opened_until - now).total_seconds())
            raise CircuitBreakerOpenError(circuit_key, max(1, remaining))

    try:
        result = operation()
    except Exception:
        with _state_lock:
            state = _state.setdefault(circuit_key, _BreakerState())
            state.failure_count += 1
            if state.failure_count >= threshold:
                state.opened_until = now + timedelta(seconds=open_duration)
        raise

    with _state_lock:
        state = _state.setdefault(circuit_key, _BreakerState())
        state.failure_count = 0
        state.opened_until = None

    return result

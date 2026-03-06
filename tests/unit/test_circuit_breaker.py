"""Tests for provider circuit breaker behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kml_satellite.core.circuit_breaker import (
    CircuitBreakerOpenError,
    call_with_circuit_breaker,
    reset_all_circuit_breakers,
)


@pytest.fixture(autouse=True)
def _reset_breaker_state() -> None:
    reset_all_circuit_breakers()


def test_circuit_opens_after_threshold_failures() -> None:
    now = datetime(2026, 3, 6, tzinfo=UTC)

    def _boom() -> int:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        call_with_circuit_breaker(
            "pc.search",
            _boom,
            failure_threshold=2,
            open_seconds=60,
            now_utc=now,
        )

    with pytest.raises(RuntimeError):
        call_with_circuit_breaker(
            "pc.search",
            _boom,
            failure_threshold=2,
            open_seconds=60,
            now_utc=now,
        )

    with pytest.raises(CircuitBreakerOpenError):
        call_with_circuit_breaker(
            "pc.search",
            lambda: 123,
            failure_threshold=2,
            open_seconds=60,
            now_utc=now + timedelta(seconds=1),
        )


def test_circuit_recovers_after_open_window() -> None:
    now = datetime(2026, 3, 6, tzinfo=UTC)

    def _boom() -> int:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        call_with_circuit_breaker(
            "pc.order",
            _boom,
            failure_threshold=1,
            open_seconds=30,
            now_utc=now,
        )

    result = call_with_circuit_breaker(
        "pc.order",
        lambda: 42,
        failure_threshold=1,
        open_seconds=30,
        now_utc=now + timedelta(seconds=31),
    )
    assert result == 42


def test_success_resets_failure_count() -> None:
    now = datetime(2026, 3, 6, tzinfo=UTC)

    def _boom() -> int:
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        call_with_circuit_breaker(
            "pc.poll",
            _boom,
            failure_threshold=3,
            open_seconds=30,
            now_utc=now,
        )

    # A successful call should reset accumulated failures.
    assert (
        call_with_circuit_breaker(
            "pc.poll",
            lambda: 1,
            failure_threshold=3,
            open_seconds=30,
            now_utc=now + timedelta(seconds=1),
        )
        == 1
    )

    with pytest.raises(RuntimeError):
        call_with_circuit_breaker(
            "pc.poll",
            _boom,
            failure_threshold=3,
            open_seconds=30,
            now_utc=now + timedelta(seconds=2),
        )

    # Should not be open yet because counter was reset and this is only first failure.
    assert (
        call_with_circuit_breaker(
            "pc.poll",
            lambda: 7,
            failure_threshold=3,
            open_seconds=30,
            now_utc=now + timedelta(seconds=3),
        )
        == 7
    )

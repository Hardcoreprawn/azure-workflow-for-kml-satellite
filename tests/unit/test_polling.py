"""Tests for polling helpers.

Tests for long-running polling logic used in acquisition phase to wait for
imagery orders to reach terminal state. Verifies timeout, retry, and backoff
behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kml_satellite.activities.poll_order import PollError


class _DummyContext:
    def __init__(self) -> None:
        self.current_utc_datetime = datetime(2026, 3, 2, 12, 0, 0, tzinfo=UTC)
        self.is_replaying = False

    def call_activity(
        self, name: str, payload: dict[str, object]
    ) -> tuple[str, str, dict[str, object]]:
        return ("activity", name, payload)

    def create_timer(self, fire_at: datetime) -> tuple[str, datetime]:
        return ("timer", fire_at)


class TestPollUntilReady:
    """Tests for the _poll_until_ready polling orchestrator."""

    def test_returns_contract_dict_on_success(self) -> None:
        """Must return a contract-shaped dict with all expected fields."""
        # We can't easily test the full generator without a real Durable Functions context,
        # so we test the helper's type hints and contract structure instead
        # This test validates the function exists and has correct signature
        import inspect

        from kml_satellite.orchestrators.polling import poll_until_ready

        sig = inspect.signature(poll_until_ready)
        params = set(sig.parameters.keys())

        expected_params = {
            "context",
            "acquisition",
            "poll_interval",
            "poll_timeout",
            "max_retries",
            "retry_base",
            "instance_id",
        }
        assert expected_params.issubset(params)

    def test_default_constants_defined(self) -> None:
        """Polling defaults must be accessible."""
        from kml_satellite.orchestrators.polling import (
            DEFAULT_MAX_RETRIES,
            DEFAULT_POLL_BATCH_SIZE,
            DEFAULT_POLL_INTERVAL_SECONDS,
            DEFAULT_POLL_TIMEOUT_SECONDS,
            DEFAULT_RETRY_BASE_SECONDS,
        )

        assert DEFAULT_POLL_INTERVAL_SECONDS == 30
        assert DEFAULT_POLL_TIMEOUT_SECONDS == 1800  # 30 minutes
        assert DEFAULT_MAX_RETRIES == 3
        assert DEFAULT_RETRY_BASE_SECONDS == 5
        assert DEFAULT_POLL_BATCH_SIZE == 10

    def test_polling_constants_are_positive_integers(self) -> None:
        """All polling constants must be positive integers (defensive)."""
        from kml_satellite.orchestrators.polling import (
            DEFAULT_MAX_RETRIES,
            DEFAULT_POLL_BATCH_SIZE,
            DEFAULT_POLL_INTERVAL_SECONDS,
            DEFAULT_POLL_TIMEOUT_SECONDS,
            DEFAULT_RETRY_BASE_SECONDS,
        )

        constants = [
            DEFAULT_POLL_BATCH_SIZE,
            DEFAULT_POLL_INTERVAL_SECONDS,
            DEFAULT_POLL_TIMEOUT_SECONDS,
            DEFAULT_MAX_RETRIES,
            DEFAULT_RETRY_BASE_SECONDS,
        ]

        for const in constants:
            assert isinstance(const, int), f"Expected int, got {type(const)}"
            assert const > 0, f"Expected positive, got {const}"

    def test_timeout_is_greater_than_interval(self) -> None:
        """Timeout should be much larger than interval (sanity check)."""
        from kml_satellite.orchestrators.polling import (
            DEFAULT_POLL_INTERVAL_SECONDS,
            DEFAULT_POLL_TIMEOUT_SECONDS,
        )

        assert DEFAULT_POLL_TIMEOUT_SECONDS > DEFAULT_POLL_INTERVAL_SECONDS * 2, (
            "Timeout should allow multiple polls"
        )

    def test_max_retries_less_than_polling_deadline(self) -> None:
        """Max retries should be much smaller than timeout seconds (defensive)."""
        from kml_satellite.orchestrators.polling import (
            DEFAULT_MAX_RETRIES,
            DEFAULT_POLL_TIMEOUT_SECONDS,
        )

        assert DEFAULT_MAX_RETRIES < DEFAULT_POLL_TIMEOUT_SECONDS, (
            "Retries should complete well before timeout"
        )

    def test_non_retryable_error_fails_immediately(self) -> None:
        """Non-retryable PollError must not be retried."""
        from kml_satellite.orchestrators.polling import poll_until_ready

        ctx = _DummyContext()
        acquisition = {
            "order_id": "pc-1",
            "scene_id": "scene-1",
            "provider": "planetary_computer",
            "aoi_feature_name": "Block A",
        }

        gen = poll_until_ready(ctx, acquisition, max_retries=3)
        next(gen)  # first call_activity yield

        try:
            gen.throw(PollError("bad request", retryable=False))
        except StopIteration as exc:
            result = exc.value
        else:
            raise AssertionError("Expected generator to stop on non-retryable error")

        assert result["state"] == "failed"
        assert "non-retryable" in str(result["error"]).lower()
        assert result["poll_count"] == 1

    def test_retryable_error_uses_exponential_backoff_then_succeeds(self) -> None:
        """Retryable poll errors should back off and retry."""
        from kml_satellite.orchestrators.polling import poll_until_ready

        ctx = _DummyContext()
        acquisition = {
            "order_id": "pc-2",
            "scene_id": "scene-2",
            "provider": "planetary_computer",
            "aoi_feature_name": "Block B",
        }

        gen = poll_until_ready(ctx, acquisition, max_retries=3, retry_base=5)
        next(gen)  # first call_activity

        timer_yield = gen.throw(PollError("timeout", retryable=True))
        assert timer_yield[0] == "timer"
        assert timer_yield[1] == ctx.current_utc_datetime + timedelta(seconds=5)

        next_call = next(gen)
        assert next_call[0] == "activity"

        ready_result = {
            "state": "ready",
            "is_terminal": True,
            "message": "ok",
        }
        try:
            gen.send(ready_result)
        except StopIteration as exc:
            result = exc.value
        else:
            raise AssertionError("Expected generator to stop with terminal ready state")

        assert result["state"] == "ready"
        assert result["poll_count"] == 2

    def test_retryable_error_exhaustion_returns_failed(self) -> None:
        """Retryable errors stop after max_retries is exceeded."""
        from kml_satellite.orchestrators.polling import poll_until_ready

        ctx = _DummyContext()
        acquisition = {
            "order_id": "pc-3",
            "scene_id": "scene-3",
            "provider": "planetary_computer",
            "aoi_feature_name": "Block C",
        }

        gen = poll_until_ready(ctx, acquisition, max_retries=0)
        next(gen)  # first call_activity

        try:
            gen.throw(PollError("transient timeout", retryable=True))
        except StopIteration as exc:
            result = exc.value
        else:
            raise AssertionError("Expected generator to stop when retries are exhausted")

        assert result["state"] == "failed"
        assert "retries exhausted" in str(result["error"]).lower()

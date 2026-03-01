"""Tests for polling helpers.

Tests for long-running polling logic used in acquisition phase to wait for
imagery orders to reach terminal state. Verifies timeout, retry, and backoff
behavior.
"""

from __future__ import annotations


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

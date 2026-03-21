"""Tests for AI circuit breaker (§4.8)."""

from __future__ import annotations

import time
from unittest.mock import patch

from treesight.ai.client import _CircuitBreaker


class TestCircuitBreaker:
    """Unit tests for _CircuitBreaker state machine."""

    def test_starts_closed(self) -> None:
        cb = _CircuitBreaker("test", threshold=3, cooldown=10.0)
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_stays_closed_below_threshold(self) -> None:
        cb = _CircuitBreaker("test", threshold=3, cooldown=10.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_opens_at_threshold(self) -> None:
        cb = _CircuitBreaker("test", threshold=3, cooldown=10.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self) -> None:
        cb = _CircuitBreaker("test", threshold=2, cooldown=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.06)
        assert cb.state == "half-open"
        assert cb.allow_request() is True

    def test_success_resets_to_closed(self) -> None:
        cb = _CircuitBreaker("test", threshold=2, cooldown=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.06)
        cb.record_success()
        assert cb.state == "closed"
        assert cb.allow_request() is True

    def test_failure_after_half_open_reopens(self) -> None:
        cb = _CircuitBreaker("test", threshold=2, cooldown=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        assert cb.state == "half-open"
        cb.record_failure()
        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_success_resets_consecutive_count(self) -> None:
        cb = _CircuitBreaker("test", threshold=3, cooldown=10.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.state == "closed"


class TestCircuitBreakerIntegration:
    """Test that circuit breaker integrates with AI provider calls."""

    def test_azure_skipped_when_circuit_open(self) -> None:
        from treesight.ai.client import _azure_circuit, _call_azure_ai

        # Save and restore state
        old_failures = _azure_circuit._consecutive_failures
        old_opened = _azure_circuit._opened_at
        try:
            _azure_circuit._consecutive_failures = _azure_circuit._threshold
            _azure_circuit._opened_at = time.monotonic()
            with patch.dict(
                "os.environ",
                {
                    "AZURE_AI_ENDPOINT": "https://test.openai.azure.com",
                    "AZURE_AI_API_KEY": "test-key",  # pragma: allowlist secret
                },
            ):
                # Should return None without making any HTTP call
                result = _call_azure_ai("test prompt")
                assert result is None
        finally:
            _azure_circuit._consecutive_failures = old_failures
            _azure_circuit._opened_at = old_opened

    def test_ollama_skipped_when_circuit_open(self) -> None:
        from treesight.ai.client import _call_ollama, _ollama_circuit

        old_failures = _ollama_circuit._consecutive_failures
        old_opened = _ollama_circuit._opened_at
        try:
            _ollama_circuit._consecutive_failures = _ollama_circuit._threshold
            _ollama_circuit._opened_at = time.monotonic()
            result = _call_ollama("test prompt")
            assert result is None
        finally:
            _ollama_circuit._consecutive_failures = old_failures
            _ollama_circuit._opened_at = old_opened

"""Tests for the poll_order activity.

Verifies order status checking with mocked provider adapters.

References:
    PID FR-3.9  (poll asynchronous job status)
    PID Section 7.4.7 (Unit test tier)
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from kml_satellite.activities.poll_order import PollError, poll_order
from kml_satellite.models.imagery import OrderState, OrderStatus
from kml_satellite.providers.base import ProviderError

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPollOrder(unittest.TestCase):
    """poll_order function with mocked provider."""

    @patch("kml_satellite.activities.poll_order.get_provider")
    def test_ready_state(self, mock_get_provider: MagicMock) -> None:
        """READY order returns is_terminal=True."""
        mock_provider = MagicMock()
        mock_provider.poll.return_value = OrderStatus(
            order_id="pc-SCENE_A",
            state=OrderState.READY,
            message="Available",
            progress_pct=100.0,
            updated_at=datetime.now(UTC),
        )
        mock_get_provider.return_value = mock_provider

        result = poll_order({"order_id": "pc-SCENE_A", "provider": "planetary_computer"})

        assert result["state"] == "ready"
        assert result["is_terminal"] is True
        assert result["progress_pct"] == 100.0

    @patch("kml_satellite.activities.poll_order.get_provider")
    def test_pending_state(self, mock_get_provider: MagicMock) -> None:
        """PENDING order returns is_terminal=False."""
        mock_provider = MagicMock()
        mock_provider.poll.return_value = OrderStatus(
            order_id="sw-ORDER_1",
            state=OrderState.PENDING,
            message="Processing",
            progress_pct=45.0,
        )
        mock_get_provider.return_value = mock_provider

        result = poll_order({"order_id": "sw-ORDER_1", "provider": "skywatch"})

        assert result["state"] == "pending"
        assert result["is_terminal"] is False

    @patch("kml_satellite.activities.poll_order.get_provider")
    def test_failed_state(self, mock_get_provider: MagicMock) -> None:
        """FAILED order returns is_terminal=True."""
        mock_provider = MagicMock()
        mock_provider.poll.return_value = OrderStatus(
            order_id="sw-ORDER_2",
            state=OrderState.FAILED,
            message="Rejected by provider",
            progress_pct=0.0,
        )
        mock_get_provider.return_value = mock_provider

        result = poll_order({"order_id": "sw-ORDER_2", "provider": "skywatch"})

        assert result["state"] == "failed"
        assert result["is_terminal"] is True

    @patch("kml_satellite.activities.poll_order.get_provider")
    def test_cancelled_state(self, mock_get_provider: MagicMock) -> None:
        """CANCELLED order returns is_terminal=True."""
        mock_provider = MagicMock()
        mock_provider.poll.return_value = OrderStatus(
            order_id="sw-ORDER_3",
            state=OrderState.CANCELLED,
            message="Timed out",
        )
        mock_get_provider.return_value = mock_provider

        result = poll_order({"order_id": "sw-ORDER_3", "provider": "skywatch"})

        assert result["state"] == "cancelled"
        assert result["is_terminal"] is True

    def test_missing_order_id_raises(self) -> None:
        """Missing order_id → PollError."""
        with self.assertRaises(PollError) as ctx:
            poll_order({"provider": "pc"})
        assert "order_id is missing" in ctx.exception.message

    def test_missing_provider_raises(self) -> None:
        """Missing provider → PollError."""
        with self.assertRaises(PollError) as ctx:
            poll_order({"order_id": "x"})
        assert "provider name is missing" in ctx.exception.message

    @patch("kml_satellite.activities.poll_order.get_provider")
    def test_provider_error_propagates(self, mock_get_provider: MagicMock) -> None:
        """ProviderError during poll → PollError with retryable flag."""
        mock_provider = MagicMock()
        mock_provider.poll.side_effect = ProviderError("pc", "API timeout", retryable=True)
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(PollError) as ctx:
            poll_order({"order_id": "x", "provider": "planetary_computer"})
        assert ctx.exception.retryable is True

    @patch("kml_satellite.activities.poll_order.get_provider")
    def test_provider_name_override(self, mock_get_provider: MagicMock) -> None:
        """provider_name kwarg overrides payload provider."""
        mock_provider = MagicMock()
        mock_provider.poll.return_value = OrderStatus(order_id="x", state=OrderState.READY)
        mock_get_provider.return_value = mock_provider

        poll_order(
            {"order_id": "x", "provider": "wrong"},
            provider_name="skywatch",
        )
        mock_get_provider.assert_called_once()
        assert mock_get_provider.call_args[0][0] == "skywatch"

    @patch("kml_satellite.activities.poll_order.get_provider")
    def test_result_has_order_id(self, mock_get_provider: MagicMock) -> None:
        """Result mirrors the order_id."""
        mock_provider = MagicMock()
        mock_provider.poll.return_value = OrderStatus(order_id="pc-123", state=OrderState.READY)
        mock_get_provider.return_value = mock_provider

        result = poll_order({"order_id": "pc-123", "provider": "pc"})
        assert result["order_id"] == "pc-123"

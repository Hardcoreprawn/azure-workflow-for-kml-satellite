"""Tests for treesight.security.rate_limit."""

import datetime
from unittest.mock import MagicMock

import pytest

from treesight.security.rate_limit import RateLimiter, TableRateLimiter, get_client_ip

# ---------------------------------------------------------------------------
# get_client_ip
# ---------------------------------------------------------------------------


class TestGetClientIp:
    def _make_req(self, headers: dict[str, str]) -> MagicMock:
        req = MagicMock()
        req.headers = headers
        return req

    def test_prefers_azure_header(self):
        req = self._make_req(
            {
                "X-Azure-ClientIP": "10.0.0.1",
                "X-Forwarded-For": "192.168.1.1, 172.16.0.1",
            }
        )
        assert get_client_ip(req) == "10.0.0.1"

    def test_uses_rightmost_forwarded_for(self):
        req = self._make_req({"X-Forwarded-For": "spoofed.ip, 172.16.0.1, 10.0.0.2"})
        assert get_client_ip(req) == "10.0.0.2"

    def test_single_forwarded_for(self):
        req = self._make_req({"X-Forwarded-For": "192.168.1.1"})
        assert get_client_ip(req) == "192.168.1.1"

    def test_ignores_spoofable_real_ip_header(self):
        req = self._make_req({"X-Real-IP": "10.0.0.3"})
        assert get_client_ip(req) == "unknown"

    def test_returns_unknown_when_no_headers(self):
        req = self._make_req({})
        assert get_client_ip(req) == "unknown"


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_allows_within_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is False

    def test_separate_keys_independent(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip2") is True
        assert limiter.is_allowed("ip1") is False
        assert limiter.is_allowed("ip2") is False

    def test_reset_clears_state(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is False
        limiter.reset()
        assert limiter.is_allowed("ip1") is True


# ---------------------------------------------------------------------------
# TableRateLimiter — mocked Azure Table Storage
# ---------------------------------------------------------------------------


def _make_table_limiter(max_requests: int = 2, window_seconds: int = 60) -> TableRateLimiter:
    """Create a TableRateLimiter with a fully mocked TableServiceClient."""
    tsc = MagicMock()
    tsc.create_table_if_not_exists = MagicMock()
    tsc.get_table_client = MagicMock(return_value=MagicMock())
    return TableRateLimiter(
        max_requests=max_requests,
        window_seconds=window_seconds,
        limiter_name="test",
        table_service_client=tsc,
    )


def _future_window_end() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=120)


def _expired_window_end() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)


class TestTableRateLimiter:
    def test_first_request_creates_entity_and_allows(self):
        from azure.core.exceptions import ResourceNotFoundError

        limiter = _make_table_limiter(max_requests=2)
        limiter._table.get_entity.side_effect = ResourceNotFoundError()
        limiter._table.create_entity = MagicMock()

        assert limiter.is_allowed("10.0.0.1") is True
        limiter._table.create_entity.assert_called_once()

    def test_allows_within_limit(self):
        limiter = _make_table_limiter(max_requests=3)
        entity = {
            "PartitionKey": "test",
            "RowKey": "10.0.0.1",
            "count": 2,
            "window_end": _future_window_end(),
            "etag": "abc",
        }
        limiter._table.get_entity.return_value = entity
        limiter._table.update_entity = MagicMock()

        assert limiter.is_allowed("10.0.0.1") is True

    def test_blocks_at_limit(self):
        limiter = _make_table_limiter(max_requests=3)
        entity = {
            "PartitionKey": "test",
            "RowKey": "10.0.0.1",
            "count": 3,
            "window_end": _future_window_end(),
            "etag": "abc",
        }
        limiter._table.get_entity.return_value = entity

        assert limiter.is_allowed("10.0.0.1") is False

    def test_expired_window_resets_counter(self):
        limiter = _make_table_limiter(max_requests=2)
        entity = {
            "PartitionKey": "test",
            "RowKey": "10.0.0.1",
            "count": 99,
            "window_end": _expired_window_end(),
            "etag": "abc",
        }
        limiter._table.get_entity.return_value = entity
        limiter._table.update_entity = MagicMock()

        assert limiter.is_allowed("10.0.0.1") is True
        # count should be reset to 1 in the updated entity
        call_args = limiter._table.update_entity.call_args[0][0]
        assert call_args["count"] == 1

    def test_retries_on_etag_conflict_then_allows(self):
        from azure.core.exceptions import ResourceModifiedError

        limiter = _make_table_limiter(max_requests=3)
        entity_ok = {
            "PartitionKey": "test",
            "RowKey": "10.0.0.1",
            "count": 1,
            "window_end": _future_window_end(),
            "etag": "abc",
        }
        # First call raises conflict; second succeeds.
        limiter._table.get_entity.side_effect = [
            ResourceModifiedError(),
            entity_ok,
        ]
        limiter._table.update_entity = MagicMock()

        assert limiter.is_allowed("10.0.0.1") is True

    def test_fails_open_after_all_retries_exhausted(self):
        from azure.core.exceptions import ResourceModifiedError

        limiter = _make_table_limiter(max_requests=2)
        limiter._table.get_entity.side_effect = ResourceModifiedError()

        # All _MAX_RETRIES attempts fail — should fail open (allow).
        assert limiter.is_allowed("10.0.0.1") is True

    def test_requires_connection_string_or_client(self):
        with pytest.raises(ValueError, match="connection_string or table_service_client"):
            TableRateLimiter(
                max_requests=5,
                window_seconds=60,
                limiter_name="test",
            )

    def test_rejects_unsafe_limiter_name(self):
        tsc = MagicMock()
        with pytest.raises(ValueError, match="limiter_name must contain only"):
            TableRateLimiter(
                max_requests=5,
                window_seconds=60,
                limiter_name="bad name'injection",
                table_service_client=tsc,
            )

    def test_separate_limiter_names_are_independent(self):
        from azure.core.exceptions import ResourceNotFoundError

        def _make_tsc():
            tsc = MagicMock()
            tsc.create_table_if_not_exists = MagicMock()
            tsc.get_table_client = MagicMock(return_value=MagicMock())
            return tsc

        limiter_a = TableRateLimiter(2, 60, "limiter_a", table_service_client=_make_tsc())
        limiter_b = TableRateLimiter(2, 60, "limiter_b", table_service_client=_make_tsc())

        limiter_a._table.get_entity.side_effect = ResourceNotFoundError()
        limiter_a._table.create_entity = MagicMock()
        limiter_b._table.get_entity.side_effect = ResourceNotFoundError()
        limiter_b._table.create_entity = MagicMock()

        assert limiter_a.is_allowed("10.0.0.1") is True
        assert limiter_b.is_allowed("10.0.0.1") is True

        # Each limiter should have created its entity with its own partition key.
        a_entity = limiter_a._table.create_entity.call_args[0][0]
        b_entity = limiter_b._table.create_entity.call_args[0][0]
        assert a_entity["PartitionKey"] == "limiter_a"
        assert b_entity["PartitionKey"] == "limiter_b"

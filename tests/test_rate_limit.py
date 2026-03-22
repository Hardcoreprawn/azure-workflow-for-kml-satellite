"""Tests for treesight.security.rate_limit."""

from unittest.mock import MagicMock

from treesight.security.rate_limit import RateLimiter, get_client_ip

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

    def test_falls_back_to_real_ip(self):
        req = self._make_req({"X-Real-IP": "10.0.0.3"})
        assert get_client_ip(req) == "10.0.0.3"

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

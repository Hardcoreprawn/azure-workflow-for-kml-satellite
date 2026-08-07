"""Tests for the UX journeys smoke script (pure logic only).

Real page loads and browser automation are exercised for real by
``make ux-smoke`` against a running dev stack, not something worth
mocking in unit tests — only the decision logic is unit-tested here.
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("playwright")

from scripts.ux_journeys import (
    API_CHECKS,
    AUTH_GATE_MARKERS,
    PAGE_JOURNEYS,
    ApiCheck,
    _is_noise,
    print_report,
    run_api_check,
)


class _FakeConsoleMessage:
    def __init__(self, type_: str, text: str) -> None:
        self.type = type_
        self.text = text


class TestIsNoise:
    def test_non_error_messages_are_noise(self):
        assert _is_noise(_FakeConsoleMessage("warning", "anything")) is True

    def test_clientid_error_is_noise(self):
        message = _FakeConsoleMessage("error", "MSAL clientId is empty")
        assert _is_noise(message) is True

    def test_unpkg_error_is_noise(self):
        message = _FakeConsoleMessage("error", "Failed to load https://unpkg.com/leaflet")
        assert _is_noise(message) is True

    def test_401_error_is_noise(self):
        """REQUIRE_AUTH/CIAM are both unset in local dev, so protected
        endpoints legitimately 401 for every page load; that's expected
        here, not a page-breaking regression."""
        message = _FakeConsoleMessage("error", "Failed to load resource: 401 (Unauthorized)")
        assert _is_noise(message) is True

    def test_unrelated_error_is_not_noise(self):
        message = _FakeConsoleMessage("error", "Uncaught TypeError: x is not a function")
        assert _is_noise(message) is False


class TestRunApiCheck:
    def _client(self, status_code: int) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code)

        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_passes_when_status_matches(self):
        check = ApiCheck("example", "GET", "/api/health", 200)
        with self._client(200) as client:
            result = run_api_check(client, "http://func", "http://web", check)
        assert result.ok is True

    def test_fails_when_status_differs(self):
        check = ApiCheck("example", "GET", "/api/health", 200)
        with self._client(503) as client:
            result = run_api_check(client, "http://func", "http://web", check)
        assert result.ok is False
        assert "503" in result.detail

    def test_uses_web_base_when_requested(self):
        check = ApiCheck("example", "GET", "/api-config.json", 200, base="web")
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            return httpx.Response(200)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            run_api_check(client, "http://func", "http://web", check)
        assert seen_urls == ["http://web/api-config.json"]

    def test_reports_transport_errors_as_failures(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        check = ApiCheck("example", "GET", "/api/health", 200)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = run_api_check(client, "http://func", "http://web", check)
        assert result.ok is False
        assert "request error" in result.detail


class TestJourneyDefinitions:
    def test_every_page_path_is_absolute(self):
        for journey in PAGE_JOURNEYS:
            assert journey.path.startswith("/"), journey.name

    def test_every_api_path_is_absolute(self):
        for check in API_CHECKS:
            assert check.path.startswith("/"), check.name

    def test_auth_gate_markers_cover_both_observed_local_dev_states(self):
        # /account/ shows a real sign-in gate; /eudr/ and /app/ auto-bypass
        # to a "Local developer" notice when no CIAM client id is
        # configured (website/js/app-msal.js renderLocalDevUI). Both are
        # valid signed-out states this script must accept.
        assert any("Sign In" in marker for marker in AUTH_GATE_MARKERS)
        assert any("Local developer" in marker for marker in AUTH_GATE_MARKERS)

    def test_covers_every_app_surface(self):
        paths = {journey.path for journey in PAGE_JOURNEYS}
        assert "/" in paths, "marketing/host site not covered"
        assert "/eudr/" in paths, "EUDR app not covered"
        assert "/app/" in paths, "conservation app not covered"
        assert "/account/" in paths, "account/settings app not covered"


class TestPrintReport:
    def test_returns_true_when_everything_passed(self, capsys: pytest.CaptureFixture[str]):
        api_result = run_api_check(
            httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
            "http://func",
            "http://web",
            ApiCheck("ok", "GET", "/api/health", 200),
        )
        assert print_report([], [api_result]) is True

    def test_returns_false_when_something_failed(self):
        api_result = run_api_check(
            httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
            "http://func",
            "http://web",
            ApiCheck("broken", "GET", "/api/health", 200),
        )
        assert print_report([], [api_result]) is False

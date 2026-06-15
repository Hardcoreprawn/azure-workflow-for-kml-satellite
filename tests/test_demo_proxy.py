"""SSRF hardening tests for the /api/proxy endpoint in blueprints/demo.py.

Covers the acceptance criteria from issue #784:
  - blocked host returns 4xx
  - IMDS IP (169.254.169.254) and link-local ranges blocked
  - non-https scheme rejected
  - oversized upstream response rejected
  - disallowed upstream content-type rejected
  - userinfo (user@host) bypass rejected
  - IDN homograph attacks rejected
  - private/reserved IP ranges blocked
  - happy-path: allowlisted domain returns 200
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_test_request

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _proxy_req(url: str) -> object:
    """Build a GET request to /api/proxy?url=<url>."""
    return make_test_request(
        "/api/proxy",
        method="GET",
        params={"url": url},
        auth_header=None,
        principal_user_id=None,
    )


def _mock_upstream(
    status: int = 200,
    content_type: str = "application/json",
    body: bytes = b'{"ok": true}',
) -> MagicMock:
    """Return a mock response that looks like a successful upstream reply."""
    raw = MagicMock()
    raw.read.return_value = body

    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"Content-Type": content_type}
    resp.raw = raw
    return resp


# ---------------------------------------------------------------------------
# URL / domain validation tests
# ---------------------------------------------------------------------------


class TestProxyBlockedHost:
    """Non-allowlisted hosts must be rejected before any network call."""

    def test_unknown_domain_returns_403(self):
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("https://evil.com/data"))
        assert resp.status_code == 403
        mock_get.assert_not_called()

    def test_suffix_overlap_rejected(self):
        """evil-environment.data.gov.uk must not match environment.data.gov.uk."""
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("https://evil-environment.data.gov.uk/data"))
        assert resp.status_code == 403
        mock_get.assert_not_called()

    def test_missing_url_parameter_returns_400(self):
        from blueprints.demo import cors_proxy

        req = make_test_request(
            "/api/proxy", method="GET", auth_header=None, principal_user_id=None
        )
        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            resp = cors_proxy(req)
        assert resp.status_code == 400


class TestProxySchemeEnforcement:
    """Only https:// may be proxied."""

    def test_http_scheme_rejected(self):
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("http://environment.data.gov.uk/data"))
        assert resp.status_code == 400
        mock_get.assert_not_called()

    def test_ftp_scheme_rejected(self):
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("ftp://environment.data.gov.uk/data"))
        assert resp.status_code == 400
        mock_get.assert_not_called()

    def test_javascript_scheme_rejected(self):
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("javascript:alert(1)"))
        assert resp.status_code == 400
        mock_get.assert_not_called()


class TestProxyImdsAndPrivateAddresses:
    """IMDS and all RFC-1918 / link-local ranges must be explicitly blocked."""

    @pytest.mark.parametrize(
        "host",
        [
            "169.254.169.254",  # Azure IMDS
            "169.254.0.1",  # link-local
            "127.0.0.1",  # loopback
            "127.1.2.3",
            "10.0.0.1",  # RFC-1918
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "0.0.0.1",  # reserved
            "::1",  # IPv6 loopback
        ],
    )
    def test_private_ip_blocked(self, host: str):
        from blueprints.demo import cors_proxy

        url = f"https://{host}/metadata"
        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req(url))
        assert resp.status_code in (400, 403), (
            f"Expected 4xx for private host {host!r}, got {resp.status_code}"
        )
        mock_get.assert_not_called()

    def test_localhost_blocked(self):
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("https://localhost/secret"))
        assert resp.status_code in (400, 403)
        mock_get.assert_not_called()


class TestProxyUserinfoBypass:
    """Credentials in the URL (user@host) must be rejected to prevent allowlist bypass."""

    def test_userinfo_with_allowed_host_rejected(self):
        """https://evil@environment.data.gov.uk/ must be blocked."""
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("https://evil@environment.data.gov.uk/data"))
        assert resp.status_code == 400
        mock_get.assert_not_called()

    def test_userinfo_with_password_rejected(self):
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(
                    _proxy_req("******environment.data.gov.uk/data")
                )
        assert resp.status_code == 400
        mock_get.assert_not_called()


class TestProxyIdnAttacks:
    """IDN homograph attacks using unicode lookalikes must be rejected."""

    def test_unicode_lookalike_rejected(self):
        """ẹnvironment.data.gov.uk (unicode 'e' variant) must not pass."""
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(_proxy_req("https://ẹnvironment.data.gov.uk/data"))
        assert resp.status_code == 403
        mock_get.assert_not_called()

    def test_punycode_lookalike_rejected(self):
        """A Punycode-encoded lookalike domain must not bypass the allowlist."""
        from blueprints.demo import cors_proxy

        # xn-- prefix indicates an internationalized domain name
        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get") as mock_get:
                resp = cors_proxy(
                    _proxy_req("https://xn--nvironment-gcb.data.gov.uk/data")
                )
        assert resp.status_code == 403
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Response handling tests
# ---------------------------------------------------------------------------


class TestProxyResponseHandling:
    """Upstream response body and content-type must be validated."""

    def test_oversized_response_rejected(self):
        from blueprints.demo import _PROXY_MAX_RESPONSE_BYTES, cors_proxy

        oversized_body = b"x" * (_PROXY_MAX_RESPONSE_BYTES + 1)
        mock_resp = _mock_upstream(body=oversized_body, content_type="application/json")

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get", return_value=mock_resp):
                resp = cors_proxy(
                    _proxy_req("https://environment.data.gov.uk/flood-monitoring/id/floods")
                )
        assert resp.status_code == 502
        assert b"5 mib" in resp.get_body().lower()

    def test_disallowed_content_type_rejected(self):
        """Binary or unexpected content-types from upstream must be blocked."""
        from blueprints.demo import cors_proxy

        mock_resp = _mock_upstream(content_type="application/octet-stream", body=b"\x00" * 100)

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get", return_value=mock_resp):
                resp = cors_proxy(
                    _proxy_req("https://environment.data.gov.uk/flood-monitoring/id/floods")
                )
        assert resp.status_code == 502
        assert b"content-type" in resp.get_body().lower()

    def test_html_content_type_rejected(self):
        """HTML responses could be used for phishing; must be blocked."""
        from blueprints.demo import cors_proxy

        mock_resp = _mock_upstream(
            content_type="text/html; charset=utf-8",
            body=b"<html><body>error</body></html>",
        )

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get", return_value=mock_resp):
                resp = cors_proxy(
                    _proxy_req("https://api.open-meteo.com/v1/forecast?latitude=51&longitude=-1")
                )
        assert resp.status_code == 502

    @pytest.mark.parametrize(
        "content_type",
        [
            "application/json",
            "application/json; charset=utf-8",
            "application/geo+json",
            "text/plain",
            "text/csv",
            "image/png",
            "image/jpeg",
            "image/webp",
        ],
    )
    def test_allowed_content_types_pass(self, content_type: str):
        from blueprints.demo import cors_proxy

        mock_resp = _mock_upstream(content_type=content_type, body=b"data")

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get", return_value=mock_resp):
                resp = cors_proxy(
                    _proxy_req("https://environment.data.gov.uk/flood-monitoring/id/floods")
                )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Happy-path test
# ---------------------------------------------------------------------------


class TestProxyHappyPath:
    """Sanity check that a valid, allowlisted request is proxied successfully."""

    def test_allowed_domain_returns_200(self):
        from blueprints.demo import cors_proxy

        mock_resp = _mock_upstream(
            body=b'{"items": []}',
            content_type="application/json",
        )
        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get", return_value=mock_resp) as mock_get:
                resp = cors_proxy(
                    _proxy_req(
                        "https://environment.data.gov.uk/flood-monitoring/id/floods"
                    )
                )
        assert resp.status_code == 200
        mock_get.assert_called_once()
        # Confirm redirects are never followed
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs.get("allow_redirects") is False

    def test_subdomain_of_allowed_passes(self):
        from blueprints.demo import cors_proxy

        mock_resp = _mock_upstream(body=b"{}", content_type="application/json")
        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = True
            with patch("blueprints.demo.requests.get", return_value=mock_resp):
                resp = cors_proxy(
                    _proxy_req(
                        "https://sub.environment.data.gov.uk/flood-monitoring/id/floods"
                    )
                )
        assert resp.status_code == 200

    def test_options_preflight_returns_cors(self):
        from blueprints.demo import cors_proxy

        req = make_test_request(
            "/api/proxy",
            method="OPTIONS",
            auth_header=None,
            principal_user_id=None,
        )
        resp = cors_proxy(req)
        assert resp.status_code in (200, 204)

    def test_rate_limited_returns_429(self):
        from blueprints.demo import cors_proxy

        with patch("blueprints.demo.proxy_limiter") as lim:
            lim.is_allowed.return_value = False
            resp = cors_proxy(_proxy_req("https://environment.data.gov.uk/data"))
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# _is_private_address unit tests
# ---------------------------------------------------------------------------


class TestIsPrivateAddress:
    """Unit tests for the explicit IMDS / private-range guard."""

    def test_imds_ip_is_private(self):
        from blueprints.demo import _is_private_address

        assert _is_private_address("169.254.169.254")

    def test_link_local_is_private(self):
        from blueprints.demo import _is_private_address

        assert _is_private_address("169.254.0.1")

    def test_loopback_is_private(self):
        from blueprints.demo import _is_private_address

        assert _is_private_address("127.0.0.1")

    def test_rfc1918_10_is_private(self):
        from blueprints.demo import _is_private_address

        assert _is_private_address("10.0.0.1")

    def test_rfc1918_172_is_private(self):
        from blueprints.demo import _is_private_address

        assert _is_private_address("172.16.0.1")

    def test_rfc1918_192_is_private(self):
        from blueprints.demo import _is_private_address

        assert _is_private_address("192.168.1.1")

    def test_ipv6_loopback_is_private(self):
        from blueprints.demo import _is_private_address

        assert _is_private_address("::1")

    def test_public_ip_not_private(self):
        from blueprints.demo import _is_private_address

        assert not _is_private_address("8.8.8.8")

    def test_domain_name_not_private(self):
        from blueprints.demo import _is_private_address

        # Non-IP strings must not raise and must return False
        assert not _is_private_address("environment.data.gov.uk")


# ---------------------------------------------------------------------------
# _content_type_allowed unit tests
# ---------------------------------------------------------------------------


class TestContentTypeAllowed:
    """Unit tests for the response content-type guard."""

    @pytest.mark.parametrize(
        "ct",
        [
            "application/json",
            "application/json; charset=utf-8",
            "application/geo+json",
            "application/vnd.geo+json",
            "text/plain",
            "text/plain; charset=utf-8",
            "text/csv",
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
        ],
    )
    def test_allowed_types(self, ct: str):
        from blueprints.demo import _content_type_allowed

        assert _content_type_allowed(ct), f"{ct!r} should be allowed"

    @pytest.mark.parametrize(
        "ct",
        [
            "text/html",
            "text/html; charset=utf-8",
            "application/xml",
            "application/octet-stream",
            "application/zip",
            "multipart/form-data",
            "video/mp4",
            "",
        ],
    )
    def test_blocked_types(self, ct: str):
        from blueprints.demo import _content_type_allowed

        assert not _content_type_allowed(ct), f"{ct!r} should be blocked"

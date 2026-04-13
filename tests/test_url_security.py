"""Tests for treesight.security.url — centralised URL host-matching utilities."""

from __future__ import annotations

import pytest

from treesight.security.url import (
    csp_token_matches_host,
    host_in_allowlist,
    host_matches,
    parse_host,
)


class TestHostMatches:
    def test_exact_match(self):
        assert host_matches("example.com", "example.com")

    def test_subdomain_match(self):
        assert host_matches("cdn.example.com", "example.com")

    def test_deep_subdomain_match(self):
        assert host_matches("a.b.c.example.com", "example.com")

    def test_no_partial_match(self):
        assert not host_matches("evil-example.com", "example.com")

    def test_empty_hostname_rejected(self):
        assert not host_matches("", "example.com")

    def test_case_insensitive(self):
        assert host_matches("CDN.Example.COM", "example.com")

    def test_target_not_substring_of_host(self):
        assert not host_matches("example.com.evil.net", "example.com")

    def test_self_not_subdomain(self):
        assert not host_matches("notexample.com", "example.com")


class TestParseHost:
    def test_https_url(self):
        assert parse_host("https://cdn.example.com/path?q=1") == "cdn.example.com"

    def test_bare_host(self):
        assert parse_host("cdn.example.com") == "cdn.example.com"

    def test_csp_wildcard(self):
        assert parse_host("*.example.com") == "*.example.com"

    def test_csp_self(self):
        assert parse_host("'self'") == "'self'"

    def test_empty(self):
        assert parse_host("") == ""


class TestCspTokenMatchesHost:
    def test_scheme_prefixed(self):
        assert csp_token_matches_host("https://cdn.example.com", "example.com")

    def test_bare_host_exact(self):
        assert csp_token_matches_host("cdn.example.com", "cdn.example.com")

    def test_bare_host_subdomain(self):
        assert csp_token_matches_host("sub.cdn.example.com", "example.com")

    def test_no_match(self):
        assert not csp_token_matches_host("https://evil.com", "example.com")

    def test_self_no_match(self):
        assert not csp_token_matches_host("'self'", "example.com")

    @pytest.mark.parametrize(
        "token,host",
        [
            ("https://js.monitor.azure.com", "js.monitor.azure.com"),
            ("https://dc.services.visualstudio.com", "visualstudio.com"),
            ("https://login.microsoftonline.com", "login.microsoftonline.com"),
        ],
    )
    def test_real_csp_tokens(self, token, host):
        assert csp_token_matches_host(token, host)


class TestHostInAllowlist:
    _ALLOWED = frozenset({"example.com", "other.org", "api.open-meteo.com"})

    def test_exact_match(self):
        assert host_in_allowlist("example.com", self._ALLOWED)

    def test_subdomain_match(self):
        assert host_in_allowlist("cdn.example.com", self._ALLOWED)

    def test_deep_subdomain(self):
        assert host_in_allowlist("a.b.c.example.com", self._ALLOWED)

    def test_no_partial_match(self):
        assert not host_in_allowlist("evil-example.com", self._ALLOWED)

    def test_empty_rejected(self):
        assert not host_in_allowlist("", self._ALLOWED)

    def test_case_insensitive(self):
        assert host_in_allowlist("CDN.Example.COM", self._ALLOWED)

    def test_unrelated_domain_rejected(self):
        assert not host_in_allowlist("evil.com", self._ALLOWED)

    def test_fqdn_subdomain_of_entry(self):
        assert host_in_allowlist("sub.api.open-meteo.com", self._ALLOWED)


class TestProxyDomainAllowlist:
    """SSRF-prevention tests for the CORS proxy domain check.

    The proxy endpoint in blueprints/demo.py validates target URLs via
    ``_is_domain_allowed`` before fetching.  These tests verify that
    common bypass techniques are rejected.
    """

    @staticmethod
    def _check(domain: str) -> bool:
        from blueprints.demo import _is_domain_allowed

        return _is_domain_allowed(domain)

    def test_allowed_domain_passes(self):
        assert self._check("environment.data.gov.uk")

    def test_subdomain_of_allowed_passes(self):
        assert self._check("sub.environment.data.gov.uk")

    def test_unrelated_domain_rejected(self):
        assert not self._check("evil.com")

    def test_suffix_overlap_rejected(self):
        """Prevent evil-environment.data.gov.uk-style bypass."""
        assert not self._check("evil-environment.data.gov.uk")

    def test_domain_with_at_sign_rejected(self):
        """Prevent credential-in-hostname SSRF bypass."""
        assert not self._check("evil.com@environment.data.gov.uk")

    def test_empty_domain_rejected(self):
        assert not self._check("")

    def test_localhost_rejected(self):
        assert not self._check("localhost")

    def test_private_ip_rejected(self):
        assert not self._check("127.0.0.1")

    def test_internal_metadata_rejected(self):
        """Azure IMDS endpoint must never be proxied."""
        assert not self._check("169.254.169.254")

    def test_all_allowed_domains_accepted(self):
        from blueprints.demo import PROXY_ALLOWED_DOMAINS

        for domain in PROXY_ALLOWED_DOMAINS:
            assert self._check(domain), f"{domain} should be allowed"

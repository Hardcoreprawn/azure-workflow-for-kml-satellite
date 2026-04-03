"""Tests for treesight.security.url — centralised URL host-matching utilities."""

from __future__ import annotations

import pytest

from treesight.security.url import csp_token_matches_host, host_matches, parse_host


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
            ("https://treesightauth.ciamlogin.com", "treesightauth.ciamlogin.com"),
            ("https://login.microsoftonline.com", "login.microsoftonline.com"),
        ],
    )
    def test_real_csp_tokens(self, token, host):
        assert csp_token_matches_host(token, host)

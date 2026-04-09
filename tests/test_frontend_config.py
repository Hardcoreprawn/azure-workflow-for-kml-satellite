"""Regression tests for frontend deployment configuration.

These validate that the static website files are self-consistent and
correctly configured, catching the class of bugs that caused:
- SWA auth misconfiguration → login redirect fails
- CSP blocking required domains → silent failures
- CORS misconfiguration → site shows Offline
"""

import json
import re
from pathlib import Path

import pytest

from treesight.security.url import csp_token_matches_host as _csp_token_matches_host

WEBSITE = Path(__file__).resolve().parent.parent / "website"
INDEX_HTML = WEBSITE / "index.html"
LANDING_JS = WEBSITE / "js" / "landing.js"
SWA_CONFIG = WEBSITE / "staticwebapp.config.json"
HELPERS_PY = Path(__file__).resolve().parent.parent / "blueprints" / "_helpers.py"


@pytest.fixture()
def index_html():
    return INDEX_HTML.read_text()


@pytest.fixture()
def landing_js():
    return LANDING_JS.read_text()


@pytest.fixture()
def swa_config():
    return json.loads(SWA_CONFIG.read_text())


# ---------------------------------------------------------------------------
# SWA auth configuration — built-in auth via azureActiveDirectory provider
# ---------------------------------------------------------------------------


class TestSwaAuth:
    def test_aad_provider_configured(self, swa_config):
        """SWA config must have azureActiveDirectory identity provider."""
        providers = swa_config.get("auth", {}).get("identityProviders", {})
        assert "azureActiveDirectory" in providers, (
            "auth.identityProviders.azureActiveDirectory missing from staticwebapp.config.json"
        )

    def test_openid_issuer_set(self, swa_config):
        """openIdIssuer must point to the CIAM tenant OIDC endpoint."""
        aad = swa_config["auth"]["identityProviders"]["azureActiveDirectory"]
        reg = aad.get("registration", {})
        issuer = reg.get("openIdIssuer", "")
        valid = (
            issuer.startswith("https://")
            and (".ciamlogin.com/" in issuer or ".login.microsoftonline.com/" in issuer)
            and issuer.endswith("/v2.0")
        )
        assert valid, (
            "openIdIssuer must be a full https URL pointing to a valid Azure OIDC v2.0 endpoint"
        )

    def test_client_id_setting_name(self, swa_config):
        """clientIdSettingName must reference an app setting name."""
        aad = swa_config["auth"]["identityProviders"]["azureActiveDirectory"]
        reg = aad.get("registration", {})
        assert reg.get("clientIdSettingName"), "clientIdSettingName must be set"

    def test_client_secret_setting_name(self, swa_config):
        """clientSecretSettingName must reference an app setting name."""
        aad = swa_config["auth"]["identityProviders"]["azureActiveDirectory"]
        reg = aad.get("registration", {})
        assert reg.get("clientSecretSettingName"), "clientSecretSettingName must be set"

    def test_api_routes_require_auth(self, swa_config):
        """API routes (except health) must require authentication."""
        routes = swa_config.get("routes", [])
        api_routes = [
            r
            for r in routes
            if r.get("route", "").startswith("/api/") and "health" not in r.get("route", "")
        ]
        for route in api_routes:
            roles = route.get("allowedRoles", [])
            assert "authenticated" in roles, (
                f"Route {route['route']} must allow the authenticated role"
            )
            assert "anonymous" not in roles, (
                f"Route {route['route']} must not allow anonymous access"
            )

    def test_health_route_anonymous(self, swa_config):
        """Health endpoint must be accessible without authentication."""
        routes = swa_config.get("routes", [])
        health_routes = [r for r in routes if "health" in r.get("route", "")]
        assert health_routes, "No health route found in SWA config"
        for route in health_routes:
            roles = route.get("allowedRoles", [])
            assert "anonymous" in roles, (
                f"Health route {route['route']} must allow anonymous access"
            )

    def test_health_exact_route_exists(self, swa_config):
        """Exact /api/health route must exist (not just /api/health/*)."""
        routes = swa_config.get("routes", [])
        exact = [r for r in routes if r.get("route") == "/api/health"]
        assert exact, (
            "Exact /api/health route needed — /api/health/* alone may not match /api/health"
        )

    def test_no_msal_script_in_html(self, index_html):
        """MSAL.js must not be loaded — SWA built-in auth replaces it."""
        assert "msal-browser" not in index_html, (
            "index.html still loads msal-browser.min.js — remove it"
        )

    def test_no_msal_cdn_references(self, index_html):
        """No external MSAL CDN references should remain."""
        for cdn in ["alcdn.msauth.net", "cdn.jsdelivr.net/@azure/msal-browser"]:
            assert cdn not in index_html, f"Dead MSAL CDN reference found: {cdn}"


# ---------------------------------------------------------------------------
# CSP — must not reference MSAL domains (SWA auth is server-side)
# ---------------------------------------------------------------------------


class TestCsp:
    def test_frame_src_none(self, swa_config):
        """CSP frame-src should be 'none' — SWA auth uses redirects, not iframes."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        frame_match = re.search(r"frame-src\s+([^;]+)", csp)
        assert frame_match, "CSP missing frame-src directive"
        assert "'none'" in frame_match.group(1), (
            "frame-src should be 'none' — MSAL iframes no longer needed"
        )

    def test_connect_src_no_msal_domains(self, swa_config):
        """CSP connect-src must not include MSAL-specific domains."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src directive"
        sources = connect_match.group(1)
        assert "ciamlogin.com" not in sources, (
            "connect-src still references ciamlogin.com — remove (SWA handles auth)"
        )

    def test_script_src_no_dead_cdn(self, swa_config):
        """CSP script-src must not reference the deprecated MSAL CDN."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        script_match = re.search(r"script-src\s+([^;]+)", csp)
        assert script_match, "CSP missing script-src directive"
        sources = script_match.group(1).split()
        assert not any(_csp_token_matches_host(src, "alcdn.msauth.net") for src in sources), (
            "CSP still references deprecated alcdn.msauth.net CDN"
        )


# ---------------------------------------------------------------------------
# Auth integration — login/logout use SWA routes
# ---------------------------------------------------------------------------


class TestAuthConfig:
    def test_login_uses_swa_route(self, landing_js):
        """login() must redirect to /.auth/login/aad."""
        assert "/.auth/login/aad" in landing_js, (
            "login() must use SWA built-in auth route /.auth/login/aad"
        )

    def test_logout_uses_swa_route(self, landing_js):
        """logout() must redirect to /.auth/logout."""
        assert "/.auth/logout" in landing_js, (
            "logout() must use SWA built-in auth route /.auth/logout"
        )

    def test_no_msal_instance(self, landing_js):
        """landing.js must not create an MSAL PublicClientApplication."""
        assert "PublicClientApplication" not in landing_js, (
            "landing.js still creates MSAL instance — must use SWA built-in auth"
        )


# ---------------------------------------------------------------------------
# CORS — backend must include all frontend origins
# ---------------------------------------------------------------------------


class TestCorsConfig:
    def test_swa_hostname_in_cors_origins(self):
        """The SWA default hostname must be in _ALLOWED_ORIGINS."""
        src = HELPERS_PY.read_text()
        assert re.search(
            r'["\']https://polite-glacier-0d6885003\.4\.azurestaticapps\.net["\']', src
        ), "_ALLOWED_ORIGINS must contain the SWA default hostname"

    def test_custom_domain_in_cors_origins(self):
        """The custom domain must be in _ALLOWED_ORIGINS."""
        src = HELPERS_PY.read_text()
        assert re.search(r'["\']https://canopex\.hrdcrprwn\.com["\']', src), (
            "_ALLOWED_ORIGINS must contain the custom domain"
        )

"""Regression tests for frontend deployment configuration.

These validate that the static website files are self-consistent and
correctly configured, catching the class of bugs that caused:
- SWA auth misconfiguration → login redirect fails
- CSP blocking required domains → silent failures
- CORS misconfiguration → site shows Offline
"""

import json
import os
import re
from pathlib import Path

import pytest

from treesight.security.url import csp_token_matches_host as _csp_token_matches_host

WEBSITE = Path(__file__).resolve().parent.parent / "website"
INDEX_HTML = WEBSITE / "index.html"
LANDING_JS = WEBSITE / "js" / "landing.js"
APP_SHELL_JS = WEBSITE / "js" / "app-shell.js"
SWA_CONFIG = WEBSITE / "staticwebapp.config.json"
HELPERS_PY = Path(__file__).resolve().parent.parent / "blueprints" / "_helpers.py"


@pytest.fixture()
def index_html():
    return INDEX_HTML.read_text()


@pytest.fixture()
def landing_js():
    return LANDING_JS.read_text()


@pytest.fixture()
def app_shell_js():
    return APP_SHELL_JS.read_text()


@pytest.fixture()
def swa_config():
    return json.loads(SWA_CONFIG.read_text())


# ---------------------------------------------------------------------------
# SWA auth configuration — pre-configured Azure AD provider (no OIDC config)
# ---------------------------------------------------------------------------


class TestSwaAuth:
    def test_no_custom_identity_provider(self, swa_config):
        """SWA pre-configured provider: no identityProviders block needed."""
        providers = swa_config.get("auth", {}).get("identityProviders", {})
        assert not providers, (
            "identityProviders should be absent — SWA pre-configured Azure AD "
            "provider requires no custom OIDC configuration"
        )

    def test_no_swa_managed_api_routes(self, swa_config):
        """SWA must not have /api/* route rules — API lives on Container Apps FA."""
        routes = swa_config.get("routes", [])
        api_routes = [r for r in routes if r.get("route", "").startswith("/api/")]
        assert not api_routes, (
            "SWA config must not contain /api/* route rules — "
            "all API calls go cross-origin to the Container Apps FA"
        )

    def test_api_config_json_route_anonymous(self, swa_config):
        """api-config.json route must allow anonymous access for BYOF discovery."""
        routes = swa_config.get("routes", [])
        cfg_routes = [r for r in routes if r.get("route") == "/api-config.json"]
        assert cfg_routes, "api-config.json route must exist for BYOF hostname discovery"
        assert "anonymous" in cfg_routes[0].get("allowedRoles", []), (
            "api-config.json must allow anonymous access"
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
        tokens = connect_match.group(1).split()
        assert not any(_csp_token_matches_host(src, "ciamlogin.com") for src in tokens), (
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

    def test_landing_uses_api_config_json(self, landing_js):
        """landing.js must discover the Container Apps FA via /api-config.json."""
        assert "api-config.json" in landing_js, (
            "landing.js must read /api-config.json for BYOF hostname discovery"
        )

    def test_landing_forwards_client_principal(self, landing_js):
        """landing.js must forward X-MS-CLIENT-PRINCIPAL for BYOF auth."""
        assert "X-MS-CLIENT-PRINCIPAL" in landing_js, (
            "landing.js apiFetch must send X-MS-CLIENT-PRINCIPAL header"
        )

    def test_landing_uses_utf8_safe_base64(self, landing_js):
        """landing.js must use TextEncoder for UTF-8 safe base64 encoding."""
        assert "TextEncoder" in landing_js, (
            "landing.js must use TextEncoder for UTF-8 safe base64 of client principal"
        )

    def test_app_shell_forwards_client_principal(self, app_shell_js):
        """app-shell.js must forward X-MS-CLIENT-PRINCIPAL for BYOF auth."""
        assert "X-MS-CLIENT-PRINCIPAL" in app_shell_js, (
            "app-shell.js apiFetch must send X-MS-CLIENT-PRINCIPAL header"
        )

    def test_app_shell_uses_utf8_safe_base64(self, app_shell_js):
        """app-shell.js must use TextEncoder for UTF-8 safe base64 encoding."""
        assert "TextEncoder" in app_shell_js, (
            "app-shell.js must use TextEncoder for UTF-8 safe base64 of client principal"
        )

    def test_app_shell_uses_api_config_json(self, app_shell_js):
        """app-shell.js must discover the Container Apps FA via /api-config.json."""
        assert "api-config.json" in app_shell_js, (
            "app-shell.js must read /api-config.json for BYOF hostname discovery"
        )


# ---------------------------------------------------------------------------
# CORS — backend must include all frontend origins
# ---------------------------------------------------------------------------


class TestCorsConfig:
    def test_no_hardcoded_swa_hostname_in_cors_origins(self):
        """SWA hostnames must come from env, not stale code constants."""
        src = HELPERS_PY.read_text()
        assert ".azurestaticapps.net" not in src

    def test_no_hardcoded_custom_domain_in_cors_origins(self):
        """Custom domains must come from CORS_ALLOWED_ORIGINS env var, not hardcoded."""
        src = HELPERS_PY.read_text()
        assert "canopex.hrdcrprwn.com" not in src, (
            "Custom domain must not be hardcoded — it should come from "
            "CORS_ALLOWED_ORIGINS env var set by infra"
        )

    def test_cors_origins_from_env_var(self):
        """_build_allowed_origins must populate origins from CORS_ALLOWED_ORIGINS env var."""
        import importlib

        import blueprints._helpers as helpers_mod
        from tests.conftest import TEST_ORIGIN

        original_cors = os.environ.get("CORS_ALLOWED_ORIGINS", "")
        try:
            os.environ["CORS_ALLOWED_ORIGINS"] = "https://custom.example.org"
            importlib.reload(helpers_mod)
            assert "https://custom.example.org" in helpers_mod._ALLOWED_ORIGINS
        finally:
            os.environ["CORS_ALLOWED_ORIGINS"] = original_cors or f"{TEST_ORIGIN}"
            importlib.reload(helpers_mod)

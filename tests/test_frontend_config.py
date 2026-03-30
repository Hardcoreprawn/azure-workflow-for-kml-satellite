"""Regression tests for frontend deployment configuration.

These validate that the static website files are self-consistent and
correctly configured, catching the class of bugs that caused:
- MSAL CDN 404 → auth silently broken (#289)
- Missing CORS → site shows Offline (#291)
- CSP blocking MSAL iframes → silent token renewal fails
- Redirect URI mismatch → AADSTS50011
"""

import json
import re
from pathlib import Path

import pytest

WEBSITE = Path(__file__).resolve().parent.parent / "website"
INDEX_HTML = WEBSITE / "index.html"
LANDING_JS = WEBSITE / "js" / "landing.js"
MSAL_BUNDLE = WEBSITE / "js" / "msal-browser.min.js"
SWA_CONFIG = WEBSITE / "staticwebapp.config.json"
API_CONFIG = WEBSITE / "api-config.json"
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
# MSAL library — must be self-hosted, not from a dead CDN
# ---------------------------------------------------------------------------


class TestMsalBundle:
    def test_msal_bundle_exists(self):
        """The self-hosted MSAL UMD bundle must be present."""
        assert MSAL_BUNDLE.exists(), (
            "website/js/msal-browser.min.js is missing — "
            "MSAL must be self-hosted (Microsoft CDN is deprecated)"
        )

    def test_msal_bundle_not_empty(self):
        assert MSAL_BUNDLE.stat().st_size > 10_000, "MSAL bundle looks too small"

    def test_index_references_local_msal(self, index_html):
        """index.html must load MSAL from a local path, not a CDN."""
        assert "alcdn.msauth.net" not in index_html, (
            "index.html still references the deprecated Microsoft MSAL CDN"
        )
        assert "/js/msal-browser.min.js" in index_html

    def test_no_external_msal_cdn(self, index_html):
        """Ensure no CDN URL is used for MSAL (all known CDNs removed it)."""
        for cdn in ["alcdn.msauth.net", "cdn.jsdelivr.net/@azure/msal-browser"]:
            assert cdn not in index_html, f"Dead MSAL CDN reference found: {cdn}"


# ---------------------------------------------------------------------------
# CSP — must allow MSAL iframes and not reference dead CDNs
# ---------------------------------------------------------------------------


class TestCsp:
    def test_frame_src_allows_ciam(self, swa_config):
        """CSP frame-src must allow CIAM login for MSAL silent token renewal."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        frame_match = re.search(r"frame-src\s+([^;]+)", csp)
        assert frame_match, "CSP missing frame-src directive"
        frame_src = frame_match.group(1)
        assert "treesightauth.ciamlogin.com" in frame_src, (
            "frame-src must include treesightauth.ciamlogin.com for MSAL iframes"
        )
        assert "login.microsoftonline.com" in frame_src

    def test_frame_src_not_none(self, swa_config):
        """frame-src 'none' breaks MSAL silent token renewal."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        frame_match = re.search(r"frame-src\s+([^;]+)", csp)
        assert frame_match, "CSP missing frame-src directive"
        assert "'none'" not in frame_match.group(1), (
            "frame-src 'none' will block MSAL silent token renewal iframes"
        )

    def test_script_src_no_dead_cdn(self, swa_config):
        """CSP script-src must not reference the deprecated MSAL CDN."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        assert "alcdn.msauth.net" not in csp, "CSP still references deprecated alcdn.msauth.net CDN"

    def test_connect_src_allows_ciam(self, swa_config):
        """CSP connect-src must allow CIAM token endpoint calls."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src directive"
        connect_src = connect_match.group(1)
        assert "treesightauth.ciamlogin.com" in connect_src
        assert "login.microsoftonline.com" in connect_src


# ---------------------------------------------------------------------------
# Auth config — MSAL redirectUri must match app registration (no trailing /)
# ---------------------------------------------------------------------------


class TestAuthConfig:
    def test_redirect_uri_no_trailing_slash(self, landing_js):
        """MSAL redirectUri must use window.location.origin without trailing slash.

        The CIAM app registration has URIs without trailing slash.
        A mismatch causes AADSTS50011.
        """
        assert "window.location.origin + '/'" not in landing_js, (
            "redirectUri has trailing slash — will cause AADSTS50011 mismatch with app registration"
        )

    def test_ciam_tenant_configured(self, landing_js):
        """CIAM tenant name must be set in landing.js."""
        match = re.search(r"CIAM_TENANT_NAME\s*=\s*'(\w+)'", landing_js)
        assert match, "CIAM_TENANT_NAME not found in landing.js"
        assert match.group(1) != "", "CIAM_TENANT_NAME is empty"

    def test_ciam_client_id_configured(self, landing_js):
        """CIAM client ID must be set in landing.js."""
        match = re.search(r"CIAM_CLIENT_ID\s*=\s*'([^']+)'", landing_js)
        assert match, "CIAM_CLIENT_ID not found in landing.js"
        assert len(match.group(1)) > 10, "CIAM_CLIENT_ID looks too short"


# ---------------------------------------------------------------------------
# CORS — backend must include all frontend origins
# ---------------------------------------------------------------------------


class TestCorsConfig:
    def test_swa_hostname_in_cors_origins(self):
        """The SWA default hostname must be in _ALLOWED_ORIGINS."""
        src = HELPERS_PY.read_text()
        assert "polite-glacier-0d6885003.4.azurestaticapps.net" in src

    def test_custom_domain_in_cors_origins(self):
        """The custom domain must be in _ALLOWED_ORIGINS."""
        src = HELPERS_PY.read_text()
        assert "treesight.hrdcrprwn.com" in src

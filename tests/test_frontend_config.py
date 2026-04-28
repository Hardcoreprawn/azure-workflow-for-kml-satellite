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
APP_INDEX_HTML = WEBSITE / "app" / "index.html"
EUDR_INDEX_HTML = WEBSITE / "eudr" / "index.html"
LANDING_JS = WEBSITE / "js" / "landing.js"
APP_SHELL_JS = WEBSITE / "js" / "app-shell.js"
APP_RUNS_JS = WEBSITE / "js" / "app-runs.js"
APP_BILLING_JS = WEBSITE / "js" / "app-billing.js"
APP_EUDR_JS = WEBSITE / "js" / "app-eudr.js"
API_CLIENT_JS = WEBSITE / "js" / "canopex-api-client.js"
APP_MSAL_JS = WEBSITE / "js" / "app-msal.js"
SWA_CONFIG = WEBSITE / "staticwebapp.config.json"
HELPERS_PY = Path(__file__).resolve().parent.parent / "blueprints" / "_helpers.py"


@pytest.fixture()
def index_html():
    return INDEX_HTML.read_text()


@pytest.fixture()
def app_index_html():
    return APP_INDEX_HTML.read_text()


@pytest.fixture()
def eudr_index_html():
    return EUDR_INDEX_HTML.read_text()


@pytest.fixture()
def landing_js():
    return LANDING_JS.read_text()


@pytest.fixture()
def app_shell_js():
    return APP_SHELL_JS.read_text()


@pytest.fixture()
def app_runs_js():
    return APP_RUNS_JS.read_text()


@pytest.fixture()
def app_billing_js():
    return APP_BILLING_JS.read_text()


@pytest.fixture()
def app_eudr_js():
    return APP_EUDR_JS.read_text()


@pytest.fixture()
def api_client_js():
    return API_CLIENT_JS.read_text()


@pytest.fixture()
def app_auth_js():
    return APP_MSAL_JS.read_text()


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

    def test_landing_loads_msal_browser(self, index_html):
        """Landing page must load the MSAL browser SDK for CIAM auth (#710)."""
        assert "msal-browser.min.js" in index_html, (
            "index.html (landing) must load msal-browser.min.js for CIAM auth"
        )

    def test_app_html_loads_msal_browser(self, app_index_html):
        """App entrypoint must load the MSAL browser SDK before app-msal.js."""
        assert "msal-browser.min.js" in app_index_html, (
            "/app/index.html must load msal-browser.min.js for CIAM auth"
        )
        msal_pos = app_index_html.index("msal-browser.min.js")
        msal_module_pos = app_index_html.index("app-msal.js")
        assert msal_pos < msal_module_pos, (
            "msal-browser CDN script must appear before app-msal.js in /app/index.html"
        )

    def test_no_dead_msal_cdn_references(self, index_html):
        """No deprecated MSAL CDN references on the landing page."""
        assert "alcdn.msauth.net" not in index_html, (
            "Dead MSAL CDN reference found: alcdn.msauth.net"
        )


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

    def test_connect_src_allows_ciam_domain(self, swa_config):
        """CSP connect-src must include the CIAM token endpoint domain for MSAL."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src directive"
        tokens = connect_match.group(1).split()
        assert any(_csp_token_matches_host(src, "treesightauth.ciamlogin.com") for src in tokens), (
            "connect-src must include treesightauth.ciamlogin.com for MSAL token calls"
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
    def test_landing_no_swa_auth_routes(self, landing_js):
        """landing.js must not reference SWA auth routes — auth is MSAL/CIAM now."""
        assert "/.auth/login/aad" not in landing_js, (
            "landing.js must not use SWA /.auth/login/aad — auth is CIAM/MSAL"
        )

    def test_landing_marks_redirect_triggered_token_errors(self, landing_js):
        """Landing token flow must mark redirect-in-progress failures for API client."""
        assert "authRedirectTriggered" in landing_js, (
            "landing.js token refresh path must set authRedirectTriggered on redirect"
        )
        assert "acquireTokenRedirect" in landing_js, (
            "landing.js must trigger acquireTokenRedirect when silent token refresh fails"
        )

    def test_msal_module_uses_public_client_app(self):
        """app-msal.js must use MSAL PublicClientApplication for CIAM auth."""
        js = APP_MSAL_JS.read_text()
        assert "PublicClientApplication" in js, (
            "app-msal.js must create msal.PublicClientApplication for CIAM auth"
        )

    def test_msal_module_uses_login_redirect(self):
        """app-msal.js must use loginRedirect (not loginPopup) for consistent UX."""
        js = APP_MSAL_JS.read_text()
        assert "loginRedirect" in js, "app-msal.js must call loginRedirect for the MSAL login flow"

    def test_msal_module_marks_redirect_triggered_token_errors(self):
        """getToken must signal redirect-in-progress.

        Callers use this marker to avoid unauthenticated fallback calls.
        """
        js = APP_MSAL_JS.read_text()
        assert "authRedirectTriggered" in js, (
            "app-msal.js must mark redirect-in-progress token errors with authRedirectTriggered"
        )
        assert "throw buildRedirectError" in js, (
            "app-msal.js getToken must throw a redirect marker error when re-auth redirect starts"
        )

    def test_api_client_uses_api_config_json(self, api_client_js):
        """Shared API client must discover the Container Apps FA via /api-config.json."""
        assert "api-config.json" in api_client_js, (
            "canopex-api-client.js must read /api-config.json for BYOF hostname discovery"
        )

    def test_api_client_sends_bearer_token(self, api_client_js):
        """Shared API client must send Authorization: Bearer token (CIAM bearer flow)."""
        assert "Authorization" in api_client_js, (
            "canopex-api-client.js must set Authorization header for CIAM bearer flow"
        )
        assert "Bearer" in api_client_js, (
            "canopex-api-client.js must use Bearer scheme in Authorization header"
        )

    def test_api_client_no_legacy_principal_header(self, api_client_js):
        """Shared API client must not send X-MS-CLIENT-PRINCIPAL — removed in #710."""
        assert "X-MS-CLIENT-PRINCIPAL" not in api_client_js, (
            "canopex-api-client.js must not send X-MS-CLIENT-PRINCIPAL (removed in #710)"
        )

    def test_api_client_no_legacy_session_header(self, api_client_js):
        """Shared API client must not send X-Auth-Session — removed in #710."""
        assert "X-Auth-Session" not in api_client_js, (
            "canopex-api-client.js must not send X-Auth-Session (removed in #710)"
        )

    def test_api_client_accepts_get_token_injection(self, api_client_js):
        """Shared API client must expose setGetToken for dependency injection."""
        assert "setGetToken" in api_client_js, (
            "canopex-api-client.js must expose setGetToken for MSAL token injection"
        )

    def test_api_client_aborts_request_when_redirect_auth_is_in_progress(self, api_client_js):
        """API client must avoid unauthenticated fallback during redirect auth."""
        assert "authRedirectTriggered" in api_client_js, (
            "canopex-api-client.js must check for authRedirectTriggered token errors"
        )
        assert "throw tokenErr" in api_client_js, (
            "canopex-api-client.js must rethrow redirect token errors to avoid fallback 401 loops"
        )

    def test_app_shell_uses_shared_api_client(self, app_shell_js):
        """App shell should use the shared API client implementation."""
        assert "CanopexApiClient.createClient" in app_shell_js, (
            "app-shell.js must initialize the shared API client"
        )

    def test_landing_loads_shared_api_client_before_consumer(self, index_html):
        """Landing entrypoint must load shared client before landing.js."""
        api_script = '<script src="/js/canopex-api-client.js"></script>'
        landing_script = '<script src="/js/landing.js"></script>'
        assert api_script in index_html, "index.html must include shared API client script"
        assert landing_script in index_html, "index.html must include landing.js script"
        assert index_html.index(api_script) < index_html.index(landing_script), (
            "index.html must load canopex-api-client.js before landing.js"
        )

    def test_app_entry_loads_shared_api_client_before_app_shell(self, app_index_html):
        """/app entrypoint must load shared client before app-shell.js."""
        api_script = '<script src="/js/canopex-api-client.js" defer></script>'
        app_script = '<script src="/js/app-shell.js" defer></script>'
        assert api_script in app_index_html, "/app/index.html must include shared API client script"
        assert app_script in app_index_html, "/app/index.html must include app-shell.js script"
        assert app_index_html.index(api_script) < app_index_html.index(app_script), (
            "/app/index.html must load canopex-api-client.js before app-shell.js"
        )

    def test_eudr_entry_loads_shared_api_client_before_app_shell(self, eudr_index_html):
        """/eudr entrypoint must load shared client before app-shell.js."""
        api_script = '<script src="/js/canopex-api-client.js" defer></script>'
        app_script = '<script src="/js/app-shell.js" defer></script>'
        assert api_script in eudr_index_html, (
            "/eudr/index.html must include shared API client script"
        )
        assert app_script in eudr_index_html, "/eudr/index.html must include app-shell.js script"
        assert eudr_index_html.index(api_script) < eudr_index_html.index(app_script), (
            "/eudr/index.html must load canopex-api-client.js before app-shell.js"
        )

    def test_app_shell_supports_org_scope_history(self, app_runs_js):
        """EUDR dashboard should request org-scoped analysis history for portfolio triage."""
        assert "scope=' + encodeURIComponent(historyScope)" in app_runs_js, (
            "app-runs.js must include scope parameter when loading analysis history"
        )
        assert "history-org" in app_runs_js, (
            "app-runs.js must keep org history cache separate from user-scoped history cache"
        )


class TestBillingEmulationUi:
    def test_billing_module_defines_fallback_emulation_tiers(self, app_billing_js):
        """Plan emulation selector should remain usable if API omits emulation.tiers."""
        expected = "['demo', 'free', 'starter', 'pro', 'team', 'enterprise', 'eudr_pro']"
        assert expected in app_billing_js, (
            "app-billing.js must define a fallback tier list for plan emulation"
        )

    def test_billing_module_formats_eudr_pro_label(self, app_billing_js):
        """Emulation selector should render eudr_pro with a readable label."""
        assert "if (tier === 'eudr_pro') return 'EUDR Pro';" in app_billing_js, (
            "app-billing.js must render eudr_pro as EUDR Pro in plan emulation options"
        )


class TestEudrUsageConsistency:
    def test_eudr_usage_labels_include_scope(self, eudr_index_html):
        """EUDR usage card labels should explicitly communicate metric scope."""
        assert "Included parcels (current billing period)" in eudr_index_html, (
            "eudr/index.html must label included parcels as current billing period"
        )
        assert "Last 6 months (org run history)" in eudr_index_html, (
            "eudr/index.html must label history as org run history"
        )

    def test_eudr_inline_script_no_longer_depends_on_global_apifetch(self, eudr_index_html):
        """Legacy inline billing script must not wait for window.apiFetch anymore."""
        assert "window.apiFetch" not in eudr_index_html, (
            "eudr/index.html should use CanopexApiClient directly, not window.apiFetch"
        )

    def test_app_eudr_updates_hero_parcels_and_unavailable_state(self, app_eudr_js):
        """EUDR module should set hero parcel pill and clear loading state on errors."""
        assert "eudr-parcels-used" in app_eudr_js, (
            "app-eudr.js must update the hero parcels stat pill"
        )
        assert "Usage unavailable right now." in app_eudr_js, (
            "app-eudr.js must clear loading text when usage fetch fails"
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

        custom_origin = "https://custom.example.org"
        original_cors = os.environ.get("CORS_ALLOWED_ORIGINS", "")
        try:
            os.environ["CORS_ALLOWED_ORIGINS"] = custom_origin
            importlib.reload(helpers_mod)
            # Set membership (not substring) — _ALLOWED_ORIGINS is set[str]
            assert custom_origin in helpers_mod._ALLOWED_ORIGINS
        finally:
            os.environ["CORS_ALLOWED_ORIGINS"] = original_cors or f"{TEST_ORIGIN}"
            importlib.reload(helpers_mod)


# ---------------------------------------------------------------------------
# Security headers — validate defensive header configuration
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_xss_protection_disabled(self, swa_config):
        """X-XSS-Protection must be '0' — deprecated header that can cause issues."""
        headers = swa_config["globalHeaders"]
        assert headers.get("X-XSS-Protection") == "0", (
            "X-XSS-Protection must be explicitly set to '0' to disable the "
            "deprecated XSS auditor — CSP provides real protection"
        )

    def test_x_robots_tag_on_app(self, swa_config):
        """The /app/* route must set X-Robots-Tag to prevent indexing."""
        routes = swa_config.get("routes", [])
        app_routes = [r for r in routes if r.get("route") == "/app/*"]
        assert app_routes, "/app/* route must exist"
        headers = app_routes[0].get("headers", {})
        assert "noindex" in headers.get("X-Robots-Tag", ""), (
            "/app/* must have X-Robots-Tag: noindex to prevent search engine indexing"
        )

    def test_x_robots_tag_on_eudr(self, swa_config):
        """The /eudr/* route must set X-Robots-Tag to prevent indexing."""
        routes = swa_config.get("routes", [])
        eudr_routes = [r for r in routes if r.get("route") == "/eudr/*"]
        assert eudr_routes, "/eudr/* route must exist"
        headers = eudr_routes[0].get("headers", {})
        assert "noindex" in headers.get("X-Robots-Tag", ""), (
            "/eudr/* must have X-Robots-Tag: noindex to prevent search engine indexing"
        )


# ---------------------------------------------------------------------------
# Static discovery files — robots.txt, security.txt, sitemap.xml
# ---------------------------------------------------------------------------


class TestStaticDiscoveryFiles:
    def test_robots_txt_exists(self):
        assert (WEBSITE / "robots.txt").is_file(), "robots.txt must exist"

    def test_robots_txt_disallows_app(self):
        content = (WEBSITE / "robots.txt").read_text()
        assert "Disallow: /app/" in content

    def test_robots_txt_disallows_eudr(self):
        content = (WEBSITE / "robots.txt").read_text()
        assert "Disallow: /eudr/" in content

    def test_sitemap_xml_exists(self):
        assert (WEBSITE / "sitemap.xml").is_file(), "sitemap.xml must exist"

    def test_security_txt_exists(self):
        assert (WEBSITE / ".well-known" / "security.txt").is_file(), (
            ".well-known/security.txt must exist"
        )

    def test_security_txt_has_contact(self):
        content = (WEBSITE / ".well-known" / "security.txt").read_text()
        assert "Contact:" in content, "security.txt must include a Contact field"

    def test_nav_fallback_excludes_static_files(self, swa_config):
        """Navigation fallback must exclude static discovery files."""
        excludes = swa_config["navigationFallback"]["exclude"]
        for path in ["/robots.txt", "/sitemap.xml", "/.well-known/*"]:
            assert path in excludes, f"{path} must be in navigationFallback.exclude"


# ---------------------------------------------------------------------------
# EUDR app entry point
# ---------------------------------------------------------------------------


class TestEudrEntryPoint:
    def test_eudr_index_exists(self):
        assert (WEBSITE / "eudr" / "index.html").is_file(), (
            "website/eudr/index.html must exist as the EUDR app entry point"
        )

    def test_eudr_index_has_data_eudr_app(self):
        content = (WEBSITE / "eudr" / "index.html").read_text()
        assert "data-eudr-app" in content, (
            "eudr/index.html <body> must have data-eudr-app attribute to lock EUDR mode"
        )

    def test_eudr_index_loads_app_shell(self):
        content = (WEBSITE / "eudr" / "index.html").read_text()
        assert "app-shell.js" in content, "eudr/index.html must load the shared app-shell.js module"

    def test_app_entrypoints_load_runtime_before_shell(self):
        app_content = (WEBSITE / "app" / "index.html").read_text()
        eudr_content = (WEBSITE / "eudr" / "index.html").read_text()

        assert "app-runtime.js" in app_content, "app/index.html must load app-runtime.js"
        assert "app-shell.js" in app_content, "app/index.html must load app-shell.js"
        assert app_content.index("app-runtime.js") < app_content.index("app-shell.js"), (
            "app/index.html must load app-runtime.js before app-shell.js"
        )

        assert "app-runtime.js" in eudr_content, "eudr/index.html must load app-runtime.js"
        assert "app-shell.js" in eudr_content, "eudr/index.html must load app-shell.js"
        assert eudr_content.index("app-runtime.js") < eudr_content.index("app-shell.js"), (
            "eudr/index.html must load app-runtime.js before app-shell.js"
        )

    def test_eudr_index_has_portfolio_summary_slots(self):
        content = (WEBSITE / "eudr" / "index.html").read_text()
        assert 'id="app-portfolio-summary"' in content
        assert 'id="app-portfolio-total-runs"' in content
        assert 'id="app-portfolio-total-parcels"' in content

    def test_app_index_has_portfolio_summary_slots(self):
        content = (WEBSITE / "app" / "index.html").read_text()
        assert 'id="app-portfolio-summary"' in content
        assert 'id="app-portfolio-active-runs"' in content
        assert 'id="app-portfolio-completed-runs"' in content

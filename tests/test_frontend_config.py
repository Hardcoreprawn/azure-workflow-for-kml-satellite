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
ACCOUNT_INDEX_HTML = WEBSITE / "account" / "index.html"
LANDING_JS = WEBSITE / "js" / "landing.js"
APP_SHELL_JS = WEBSITE / "js" / "app-shell.js"
APP_RUNS_JS = WEBSITE / "js" / "app-runs.js"
APP_BILLING_JS = WEBSITE / "js" / "app-billing.js"
APP_EUDR_JS = WEBSITE / "js" / "app-eudr.js"
APP_RUN_LIFECYCLE_JS = WEBSITE / "js" / "app-run-lifecycle.js"
APP_CORE_DOM_JS = WEBSITE / "js" / "app-core-dom.js"
API_CLIENT_JS = WEBSITE / "js" / "canopex-api-client.js"
APP_CIAM_JS = WEBSITE / "js" / "canopex-auth.js"
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
def app_run_lifecycle_js():
    return APP_RUN_LIFECYCLE_JS.read_text()


@pytest.fixture()
def app_core_dom_js():
    return APP_CORE_DOM_JS.read_text()


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
            "SWA config must not contain /api/* route rules — all API calls go cross-origin to the Container Apps FA"
        )

    def test_api_not_excluded_from_navigation_fallback(self, swa_config):
        """/api/* must not be excluded from SPA fallback (#772).

        Excluding /api/* causes SWA to forward those requests to the linked
        backend.  When the linked backend is stale or unreachable (as happens
        after the BYOF architecture migration) SWA returns 500
        "Backend call failure".  Keeping /api/* inside the SPA fallback means
        SWA returns index.html instead, and the frontend routes API calls
        cross-origin to the orchestrator via api-config.json as intended.
        """
        exclude_list = swa_config.get("navigationFallback", {}).get("exclude", [])
        api_excludes = [p for p in exclude_list if p == "/api/*" or p.startswith("/api/")]
        assert not api_excludes, (
            "navigationFallback.exclude must not contain /api/* paths — "
            "excluding them causes SWA to proxy to a stale linked backend (500). "
            "All API calls go cross-origin to the orchestrator via api-config.json."
        )

    def test_api_config_json_route_anonymous(self, swa_config):
        """api-config.json route must allow anonymous access for BYOF discovery."""
        routes = swa_config.get("routes", [])
        cfg_routes = [r for r in routes if r.get("route") == "/api-config.json"]
        assert cfg_routes, "api-config.json route must exist for BYOF hostname discovery"
        assert "anonymous" in cfg_routes[0].get("allowedRoles", []), "api-config.json must allow anonymous access"

    def test_landing_loads_msal_browser(self, index_html):
        """Landing page must load the MSAL browser SDK for CIAM auth (#710)."""
        assert "msal-browser.min.js" in index_html, "index.html (landing) must load msal-browser.min.js for CIAM auth"

    def test_landing_loads_msal_with_defer(self, index_html):
        """Landing page must load MSAL, API client, and landing.js all with defer to avoid race."""
        # Check that all three critical scripts are loaded with defer
        api_tag = '<script src="/js/canopex-api-client.js" defer></script>'
        landing_tag = '<script src="/js/landing.js" defer></script>'
        assert api_tag in index_html, "index.html must load canopex-api-client.js with defer attribute"
        assert landing_tag in index_html, "index.html must load landing.js with defer attribute"
        # Verify the MSAL script tag itself includes defer without depending on
        # exact formatting, attribute order, or fixed byte offsets.
        msal_script_with_defer = re.search(
            r'<script\b[^>]*\bsrc="[^"]*msal-browser\.min\.js"[^>]*\bdefer\b[^>]*>',
            index_html,
        )
        assert msal_script_with_defer, "index.html MSAL script must have defer attribute"

    def test_app_html_loads_msal_browser(self, app_index_html):
        """App entrypoint must load the MSAL browser SDK before app-msal.js."""
        assert "msal-browser.min.js" in app_index_html, "/app/index.html must load msal-browser.min.js for CIAM auth"
        msal_pos = app_index_html.index("msal-browser.min.js")
        msal_module_pos = app_index_html.index("app-msal.js")
        assert msal_pos < msal_module_pos, "msal-browser CDN script must appear before app-msal.js in /app/index.html"

    def test_no_dead_msal_cdn_references(self, index_html):
        """No deprecated MSAL CDN references on the landing page."""
        assert "alcdn.msauth.net" not in index_html, "Dead MSAL CDN reference found: alcdn.msauth.net"


# ---------------------------------------------------------------------------
# CSP — must not reference MSAL domains (SWA auth is server-side)
# ---------------------------------------------------------------------------


class TestCsp:
    def test_frame_src_allows_ciam_domain(self, swa_config):
        """CSP frame-src must allow the CIAM host for MSAL silent refresh."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        frame_match = re.search(r"frame-src\s+([^;]+)", csp)
        assert frame_match, "CSP missing frame-src directive"
        tokens = frame_match.group(1).split()
        assert any(_csp_token_matches_host(src, "canopex.ciamlogin.com") for src in tokens), (
            "frame-src must include canopex.ciamlogin.com for MSAL silent refresh"
        )

    def test_connect_src_allows_ciam_domain(self, swa_config):
        """CSP connect-src must include the CIAM token endpoint domain for MSAL."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src directive"
        tokens = connect_match.group(1).split()
        assert any(_csp_token_matches_host(src, "canopex.ciamlogin.com") for src in tokens), (
            "connect-src must include canopex.ciamlogin.com for MSAL token calls"
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

    def test_connect_src_no_wildcard_container_apps(self, swa_config):
        """CSP connect-src must not use *.azurecontainerapps.io wildcard.

        The wildcard matches any Container App on Azure, not just ours.
        Use the placeholder token __FUNC_HOSTNAME__ (substituted at deploy time)
        instead. See issue #573.
        """
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        assert "*.azurecontainerapps.io" not in csp, (
            "CSP connect-src must not use *.azurecontainerapps.io wildcard — "
            "pin to the specific hostname via __FUNC_HOSTNAME__ placeholder"
        )
        assert "__FUNC_HOSTNAME__" in csp, (
            "CSP connect-src must contain the __FUNC_HOSTNAME__ placeholder "
            "that is substituted with the actual Container App FQDN at deploy time"
        )

    def test_connect_src_no_wildcard_blob_storage(self, swa_config):
        """CSP connect-src must not use *.blob.core.windows.net wildcard.

        The wildcard matches any Azure Storage account globally.
        Use the placeholder token __BLOB_HOSTNAME__ (substituted at deploy time)
        instead. See issue #573.
        """
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        assert "*.blob.core.windows.net" not in csp, (
            "CSP connect-src must not use *.blob.core.windows.net wildcard — "
            "pin to the specific storage account hostname via __BLOB_HOSTNAME__ placeholder"
        )
        assert "__BLOB_HOSTNAME__" in csp, (
            "CSP connect-src must contain the __BLOB_HOSTNAME__ placeholder "
            "that is substituted with the actual storage hostname at deploy time"
        )

    def test_style_src_no_unpkg(self, swa_config):
        """CSP style-src must not reference unpkg.com now that Leaflet is self-hosted."""
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        style_match = re.search(r"style-src\s+([^;]+)", csp)
        assert style_match, "CSP missing style-src directive"
        sources = style_match.group(1).split()
        assert not any(_csp_token_matches_host(src, "unpkg.com") for src in sources), (
            "CSP style-src must not reference unpkg.com — Leaflet CSS is now self-hosted "
            "under /vendor/leaflet/leaflet.css"
        )

    def test_connect_src_still_covers_unpkg_for_msal(self, swa_config):
        """connect-src must still allow unpkg.com even though Leaflet is self-hosted.

        script-src still loads @azure/msal-browser from unpkg.com, and per
        test_connect_src_covers_cdn_domains_for_source_maps, every script-src
        CDN must also be in connect-src (source-map fetches go through
        connect-src). Removing it here would only be safe once msal-browser
        is self-hosted too — not yet the case.
        """
        csp = swa_config["globalHeaders"]["Content-Security-Policy"]
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src directive"
        sources = connect_match.group(1).split()
        assert any(_csp_token_matches_host(src, "unpkg.com") for src in sources), (
            "CSP connect-src must still allow unpkg.com while msal-browser is loaded from there via script-src"
        )

    def test_navigation_fallback_excludes_vendor(self, swa_config):
        """navigationFallback exclude list must include /vendor/* so vendor assets are served."""
        exclude = swa_config["navigationFallback"]["exclude"]
        assert "/vendor/*" in exclude, (
            "navigationFallback.exclude must include /vendor/* so self-hosted vendor "
            "assets (e.g. Leaflet) are served directly rather than rewritten to index.html"
        )


# ---------------------------------------------------------------------------
# Self-hosted vendor assets
# ---------------------------------------------------------------------------


class TestVendorLeaflet:
    """Leaflet must be self-hosted under website/vendor/leaflet/ (issue #519)."""

    VENDOR_DIR = WEBSITE / "vendor" / "leaflet"

    def test_vendor_leaflet_css_exists(self):
        """website/vendor/leaflet/leaflet.css must be present."""
        assert (self.VENDOR_DIR / "leaflet.css").is_file(), (
            "vendor/leaflet/leaflet.css is missing — run npm pack leaflet@1.9.4 and copy "
            "dist/leaflet.css into website/vendor/leaflet/"
        )

    def test_vendor_leaflet_js_exists(self):
        """website/vendor/leaflet/leaflet.js must be present."""
        assert (self.VENDOR_DIR / "leaflet.js").is_file(), (
            "vendor/leaflet/leaflet.js is missing — run npm pack leaflet@1.9.4 and copy "
            "dist/leaflet.js into website/vendor/leaflet/"
        )

    def test_vendor_leaflet_js_map_exists(self):
        """website/vendor/leaflet/leaflet.js.map must be present.

        Without it, DevTools source-map fetches for leaflet.js 404 (noisy
        but non-fatal) rather than resolving to readable source.
        """
        assert (self.VENDOR_DIR / "leaflet.js.map").is_file(), (
            "vendor/leaflet/leaflet.js.map is missing — copy dist/leaflet.js.map "
            "into website/vendor/leaflet/ alongside leaflet.js"
        )

    @pytest.mark.parametrize(
        "image_name",
        [
            "marker-icon.png",
            "marker-icon-2x.png",
            "marker-shadow.png",
            "layers.png",
            "layers-2x.png",
        ],
    )
    def test_vendor_leaflet_images_exist(self, image_name):
        """Every marker/layer image Leaflet's default icon and layer control need must be present.

        leaflet.css references layers.png/layers-2x.png directly via url();
        leaflet.js constructs the marker-icon*/marker-shadow URLs at runtime
        for the default marker icon. Missing any of these breaks map markers
        or the layer-toggle control with no test signal otherwise.
        """
        assert (self.VENDOR_DIR / "images" / image_name).is_file(), (
            f"vendor/leaflet/images/{image_name} is missing — copy dist/images/{image_name} "
            "into website/vendor/leaflet/images/"
        )

    def test_landing_uses_local_leaflet_css(self, index_html):
        """Landing page must load Leaflet CSS from /vendor/, not CDN."""
        assert "/vendor/leaflet/leaflet.css" in index_html, (
            "index.html must reference /vendor/leaflet/leaflet.css, not the unpkg CDN"
        )
        assert "unpkg.com/leaflet" not in index_html, "index.html must not reference Leaflet from unpkg.com"

    def test_landing_uses_local_leaflet_js(self, index_html):
        """Landing page must load Leaflet JS from /vendor/, not CDN."""
        assert "/vendor/leaflet/leaflet.js" in index_html, (
            "index.html must reference /vendor/leaflet/leaflet.js, not the unpkg CDN"
        )

    def test_app_uses_local_leaflet_css(self, app_index_html):
        """/app/ must load Leaflet CSS from /vendor/, not CDN."""
        assert "/vendor/leaflet/leaflet.css" in app_index_html, (
            "/app/index.html must reference /vendor/leaflet/leaflet.css, not the unpkg CDN"
        )
        assert "unpkg.com/leaflet" not in app_index_html, "/app/index.html must not reference Leaflet from unpkg.com"

    def test_app_uses_local_leaflet_js(self, app_index_html):
        """/app/ must load Leaflet JS from /vendor/, not CDN."""
        assert "/vendor/leaflet/leaflet.js" in app_index_html, (
            "/app/index.html must reference /vendor/leaflet/leaflet.js, not the unpkg CDN"
        )

    def test_eudr_uses_local_leaflet_css(self, eudr_index_html):
        """/eudr/ must load Leaflet CSS from /vendor/, not CDN.

        Regression guard: /eudr/index.html was missed in the initial
        self-hosting pass, and the CSP's style-src no longer allows
        unpkg.com — leaving it on the CDN would silently break the map
        on the EUDR evidence-review page.
        """
        assert "/vendor/leaflet/leaflet.css" in eudr_index_html, (
            "/eudr/index.html must reference /vendor/leaflet/leaflet.css, not the unpkg CDN"
        )
        assert "unpkg.com/leaflet" not in eudr_index_html, "/eudr/index.html must not reference Leaflet from unpkg.com"

    def test_eudr_uses_local_leaflet_js(self, eudr_index_html):
        """/eudr/ must load Leaflet JS from /vendor/, not CDN."""
        assert "/vendor/leaflet/leaflet.js" in eudr_index_html, (
            "/eudr/index.html must reference /vendor/leaflet/leaflet.js, not the unpkg CDN"
        )

    def test_no_page_references_leaflet_cdn(self):
        """No HTML page anywhere under website/ may reference unpkg.com/leaflet.

        Broad regression guard so a future page (or a page added after this
        test file was last updated) can't silently reintroduce the CDN
        reference that CSP's style-src no longer allows.
        """
        offenders = [
            str(html_path.relative_to(WEBSITE))
            for html_path in WEBSITE.rglob("*.html")
            if "unpkg.com/leaflet" in html_path.read_text()
        ]
        assert not offenders, f"unpkg.com/leaflet CDN reference found in: {offenders}"


# ---------------------------------------------------------------------------
# Auth integration — login/logout use SWA routes
# ---------------------------------------------------------------------------


class TestAuthConfig:
    def test_landing_no_swa_auth_routes(self, landing_js):
        """landing.js must not reference SWA auth routes — auth is MSAL/CIAM now."""
        assert "/.auth/login/aad" not in landing_js, "landing.js must not use SWA /.auth/login/aad — auth is CIAM/MSAL"

    def test_landing_delegates_msal_to_shared_module(self, landing_js):
        """landing.js must delegate MSAL primitives to window.CanopexCiam.

        The duplicated MSAL setup that used to live in landing.js was the
        root cause of cross-page sign-in races and scope drift. landing.js
        must now import everything via window.CanopexCiam.
        """
        assert "window.CanopexCiam" in landing_js, "landing.js must reference window.CanopexCiam (canopex-auth.js)"
        assert "new window.msal.PublicClientApplication" not in landing_js, (
            "landing.js must not construct its own PublicClientApplication — delegate to canopex-auth.js"
        )
        assert "loginRedirect(" not in landing_js, (
            "landing.js must not call loginRedirect directly — use CanopexCiam.login()"
        )

    def test_landing_marks_redirect_triggered_token_errors(self):
        """The shared CIAM auth module must signal redirect-in-progress errors.

        landing.js delegates to window.CanopexCiam, so the redirect-in-progress
        marker (authRedirectTriggered) is enforced in canopex-auth.js — the
        single source of truth.
        """
        js = APP_CIAM_JS.read_text()
        assert "authRedirectTriggered" in js, "canopex-auth.js token refresh path must set authRedirectTriggered"
        assert "acquireTokenRedirect" in js, (
            "canopex-auth.js must trigger acquireTokenRedirect when silent token refresh fails"
        )

    def test_landing_auth_enabled_depends_on_ciam_config(self, landing_js):
        """Landing auth gating must reflect real CIAM/MSAL config availability."""
        assert "return !!(window.msal && cfg.clientId && cfg.authority);" in landing_js, (
            "landing.js authEnabled must depend on MSAL + CIAM config presence"
        )

    def test_msal_module_uses_public_client_app(self):
        """The shared canopex-auth.js module must use MSAL PublicClientApplication."""
        js = APP_CIAM_JS.read_text()
        assert "PublicClientApplication" in js, "canopex-auth.js must create msal.PublicClientApplication for CIAM auth"

    def test_msal_module_uses_login_redirect(self):
        """The shared canopex-auth.js module must use loginRedirect (not loginPopup)."""
        js = APP_CIAM_JS.read_text()
        assert "loginRedirect" in js, "canopex-auth.js must call loginRedirect for the MSAL login flow"

    def test_msal_module_supports_signup_prompt_create(self):
        """Shared CIAM module must expose an explicit sign-up redirect path."""
        js = APP_CIAM_JS.read_text()
        assert "function signup()" in js, "canopex-auth.js must define signup() for first-visit account creation"
        assert "prompt: 'create'" in js, (
            "canopex-auth.js signup() must pass prompt:create to open account-creation flow"
        )

    def test_landing_wires_create_account_button(self, landing_js):
        """Landing UI must wire a dedicated create-account CTA to CIAM signup."""
        assert "auth-signup-btn" in landing_js, (
            "landing.js must reference #auth-signup-btn for first-visit create-account CTA"
        )
        assert "ciamAuth.signup" in landing_js, "landing.js create-account CTA must call CanopexCiam.signup()"

    def test_msal_module_marks_redirect_triggered_token_errors(self):
        """getToken must signal redirect-in-progress.

        Callers use this marker to avoid unauthenticated fallback calls.
        """
        js = APP_CIAM_JS.read_text()
        assert "authRedirectTriggered" in js, (
            "canopex-auth.js must mark redirect-in-progress token errors with authRedirectTriggered"
        )
        assert "throw buildRedirectError" in js, (
            "canopex-auth.js getToken must throw a redirect marker error when re-auth redirect starts"
        )

    def test_msal_module_get_token_waits_for_init(self):
        """getToken must wait for MSAL initialization and redirect handling."""
        js = APP_CIAM_JS.read_text()
        assert "ensureMsalReady" in js, "canopex-auth.js must define a shared ensureMsalReady helper"
        assert "var app = await ensureMsalReady();" in js, (
            "canopex-auth.js getToken must await ensureMsalReady before MSAL API calls"
        )

    def test_msal_module_supports_api_audience_config(self):
        """MSAL module must read optional API audience from injected CIAM config."""
        js = APP_CIAM_JS.read_text()
        assert "apiAudience" in js, "canopex-auth.js must parse apiAudience from canopex-ciam-config"
        assert "audience + '/User.Read'" in js, "canopex-auth.js must derive an API scope from apiAudience"

    def test_msal_module_prefers_access_token_when_api_audience_present(self):
        """Backend bearer validation requires API-audience access token when configured."""
        js = APP_CIAM_JS.read_text()
        assert "return result.accessToken || '';" in js, (
            "canopex-auth.js getToken must return the access token from silent acquisition"
        )

    def test_msal_module_surfaces_missing_audience_as_error(self):
        """When apiAudience is missing, getToken must raise — not return ''.

        Returning '' silently caused intermittent 401 floods because callers
        sent unauthenticated requests against a CIAM-protected backend.
        """
        js = APP_CIAM_JS.read_text()
        assert "throw new Error" in js and "apiAudience is not configured" in js, (
            "canopex-auth.js getToken must throw a visible error when apiAudience is missing"
        )

    def test_msal_module_uses_root_redirect_uri(self):
        """redirectUri must use window.location.origin + '/' (root only).

        Using a root redirect URI with MSAL's default navigateToLoginRequestUrl: true
        is the standard MSAL SPA pattern. It avoids CIAM AADSTS50011 errors when
        signing in from non-root pages (/eudr/, /app/, etc.). MSAL automatically
        restores the original page URL after the auth redirect completes at root.

        This replaces the old per-page redirect URI approach (PR #774) which required
        complex per-page CIAM registration and CI-time HTML injection.
        """
        js = APP_CIAM_JS.read_text()
        assert "window.location.origin + '/'" in js or 'window.location.origin + "/"' in js, (
            "canopex-auth.js must use window.location.origin + '/' as redirectUri"
        )
        assert "navigateToLoginRequestUrl" in js, (
            "canopex-auth.js must mention navigateToLoginRequestUrl for page restoration"
        )
        # Old per-page pattern must be removed
        assert "pageRedirectUri" not in js, (
            "canopex-auth.js must not use pageRedirectUri function (old per-page pattern)"
        )

    def test_msal_module_splits_update_auth_ui_render_paths(self):
        """Auth UI rendering should be split into smaller helpers."""
        js = APP_MSAL_JS.read_text()
        assert "renderLocalDevUI" in js, "app-msal.js must factor local-dev UI rendering"
        assert "renderSignedInUI" in js, "app-msal.js must factor signed-in UI rendering"
        assert "renderSignedOutUI" in js, "app-msal.js must factor signed-out UI rendering"

    def test_local_dev_ui_loads_billing_status(self):
        """renderLocalDevUI must trigger the billing fetch (#1255).

        The backend answers anonymously when REQUIRE_AUTH/CIAM are unset, so
        without this call the hero Plan/Runs/Mode cards are stuck on their
        static "Loading…" placeholder forever in local dev.
        """
        js = APP_MSAL_JS.read_text()
        local_dev_fn = js.split("function renderLocalDevUI")[1].split("function renderSignedInUI")[0]
        assert "_loadBillingStatus" in local_dev_fn, (
            "renderLocalDevUI must call _loadBillingStatus so the hero cards populate"
        )

    def test_billing_module_proceeds_without_account_when_auth_disabled(self):
        """app-billing.js's load() must not silently no-op in local dev (#1255).

        Skip only when real auth is configured but the user is signed out —
        mirrors the existing pattern in app-runs.js's loadHistory.
        """
        js = APP_BILLING_JS.read_text()
        assert "_authEnabled" in js, "app-billing.js must accept an authEnabled dependency"
        assert "&& authEnabled) return" in js, (
            "app-billing.js load() must only skip when authEnabled is true (real auth, signed out)"
        )

    def test_account_page_does_not_capture_ciam_before_it_loads(self):
        """account/index.html must not freeze `ciam` at parse time (#1256).

        canopex-auth.js loads with `defer`, so it hasn't set
        window.CanopexCiam yet when this page's own inline (non-deferred)
        script block is parsed. Capturing `window.CanopexCiam || {}` at that
        point permanently freezes `ciam` at `{}`, silently breaking every
        auth check on the page (getAccount/onAccountChange never work).
        """
        html = ACCOUNT_INDEX_HTML.read_text()
        assert "var ciam = {};" in html, (
            "account/index.html must start with an empty ciam placeholder, not "
            "window.CanopexCiam || {} (which would freeze it before canopex-auth.js, "
            "loaded with defer, has run)"
        )
        assert "ciam = window.CanopexCiam || {};" in html, (
            "account/index.html must (re)resolve ciam inside init(), after deferred scripts run"
        )

    def test_account_page_bypasses_auth_gate_in_local_dev(self):
        """account/index.html must not permanently gate local dev behind
        sign-in (#1256) — mirrors the bypass already used on /eudr/ and
        /app/ (website/js/app-msal.js renderLocalDevUI).
        """
        html = ACCOUNT_INDEX_HTML.read_text()
        assert "ciam.authEnabled === 'function' && !ciam.authEnabled()" in html, (
            "account/index.html's updateAuthUI must check authEnabled() before gating"
        )

    def test_landing_msal_script_is_pinned_and_has_sri(self, index_html):
        """Landing MSAL script must use an exact version and SRI."""
        assert "@azure/msal-browser@3.30.0/lib/msal-browser.min.js" in index_html, (
            "index.html must pin MSAL to an exact version"
        )
        assert 'integrity="sha384-' in index_html, "index.html must include SRI for the pinned MSAL script"

    def test_app_msal_script_is_pinned_and_has_sri(self, app_index_html):
        """App MSAL script must use an exact version and SRI."""
        assert "@azure/msal-browser@3.30.0/lib/msal-browser.min.js" in app_index_html, (
            "/app/index.html must pin MSAL to an exact version"
        )
        assert 'integrity="sha384-' in app_index_html, "/app/index.html must include SRI for the pinned MSAL script"

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
        assert "Bearer" in api_client_js, "canopex-api-client.js must use Bearer scheme in Authorization header"

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
        assert "setGetToken" in api_client_js, "canopex-api-client.js must expose setGetToken for MSAL token injection"

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
        assert "CanopexApiClient.createClient" in app_shell_js, "app-shell.js must initialize the shared API client"

    def test_landing_loads_shared_api_client_before_consumer(self, index_html):
        """Landing entrypoint must load shared client before landing.js."""
        api_script = '<script src="/js/canopex-api-client.js" defer></script>'
        landing_script = '<script src="/js/landing.js" defer></script>'
        assert api_script in index_html, "index.html must include shared API client script with defer"
        assert landing_script in index_html, "index.html must include landing.js script with defer"
        assert index_html.index(api_script) < index_html.index(landing_script), (
            "index.html must load canopex-api-client.js before landing.js"
        )

    def test_landing_nav_includes_create_account_cta(self, index_html):
        """Landing nav must expose a distinct create-account action for first-time users."""
        assert 'id="auth-signup-btn"' in index_html, (
            "/index.html nav auth area must include a dedicated create-account button"
        )
        assert ">Create Account<" in index_html, (
            "/index.html create-account button must have explicit copy for first-time users"
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

    # --- #757 MSAL token lifecycle tests ---

    def test_msal_module_tracks_last_token_acquired_at(self):
        """getToken must update _lastTokenAcquiredAt after a successful acquisition (#757)."""
        js = APP_CIAM_JS.read_text()
        assert "_lastTokenAcquiredAt" in js, (
            "canopex-auth.js must declare _lastTokenAcquiredAt for token age telemetry (#757)"
        )
        assert "tokenAge" in js or "_lastTokenAcquiredAt = new Date" in js, (
            "canopex-auth.js must update _lastTokenAcquiredAt when a token is acquired (#757)"
        )

    def test_msal_handle_api_error_uses_popup_not_logout(self):
        """handleApiError must use acquireTokenPopup for transparent re-auth (#757).

        Logging out on a 401 would interrupt a demo mid-session. The handler
        must instead try a popup so the user can re-authenticate in place.
        Popup logic now lives in canopex-auth.js (reauthInPlace) and
        app-msal.js handleApiError invokes it.
        """
        ciam_js = APP_CIAM_JS.read_text()
        msal_js = APP_MSAL_JS.read_text()
        assert "acquireTokenPopup" in ciam_js, (
            "canopex-auth.js reauthInPlace must call acquireTokenPopup for transparent 401 re-auth (#757)"
        )
        assert "reauthInPlace" in msal_js, (
            "app-msal.js handleApiError must delegate to CanopexCiam.reauthInPlace (#757)"
        )

    def test_msal_handle_api_error_no_immediate_logout(self):
        """handleApiError must not immediately call logoutRedirect on a 401 (#757)."""
        js = APP_MSAL_JS.read_text()
        # Find the handleApiError function body and confirm logoutRedirect is not in it.
        ha_idx = js.find("function handleApiError")
        assert ha_idx != -1, "app-msal.js must define handleApiError"
        # Scan to the next top-level function definition (heuristic: next 'function ' at col 2)
        next_fn_idx = js.find("\n  function ", ha_idx + 1)
        ha_body = js[ha_idx:next_fn_idx] if next_fn_idx != -1 else js[ha_idx:]
        assert "logoutRedirect" not in ha_body, (
            "app-msal.js handleApiError must not call logoutRedirect on 401 — use popup re-auth (#757)"
        )

    def test_msal_handle_api_error_shows_info_toast(self):
        """handleApiError must surface a non-error toast while re-authing (#757)."""
        js = APP_MSAL_JS.read_text()
        ha_idx = js.find("function handleApiError")
        next_fn_idx = js.find("\n  function ", ha_idx + 1)
        ha_body = js[ha_idx:next_fn_idx] if next_fn_idx != -1 else js[ha_idx:]
        assert "_setAnalysisStatus" in ha_body, (
            "app-msal.js handleApiError must call _setAnalysisStatus to inform the user (#757)"
        )
        assert "'info'" in ha_body, (
            "app-msal.js handleApiError must use 'info' severity for session-refresh toast (#757)"
        )

    def test_eudr_entry_loads_shared_api_client_before_app_shell(self, eudr_index_html):
        """/eudr entrypoint must load shared client before app-shell.js."""
        api_script = '<script src="/js/canopex-api-client.js" defer></script>'
        app_script = '<script src="/js/app-shell.js" defer></script>'
        assert api_script in eudr_index_html, "/eudr/index.html must include shared API client script"
        assert app_script in eudr_index_html, "/eudr/index.html must include app-shell.js script"
        assert eudr_index_html.index(api_script) < eudr_index_html.index(app_script), (
            "/eudr/index.html must load canopex-api-client.js before app-shell.js"
        )

    def test_eudr_entry_uses_msal_not_legacy_auth(self, eudr_index_html):
        """EUDR app must use MSAL bearer flow, not legacy SWA auth module."""
        assert "app-msal.js" in eudr_index_html, "/eudr/index.html must load app-msal.js for CIAM bearer auth"
        assert "app-auth.js" not in eudr_index_html, (
            "/eudr/index.html must not load app-auth.js (legacy SWA auth removed in #710)"
        )
        msal_pos = eudr_index_html.index("app-msal.js")
        app_shell_pos = eudr_index_html.index("app-shell.js")
        assert msal_pos < app_shell_pos, "/eudr/index.html must load app-msal.js before app-shell.js"

    def test_eudr_entry_injects_ciam_config_script(self, eudr_index_html):
        """EUDR entrypoint must include CIAM config script element for MSAL initialization."""
        assert 'id="canopex-ciam-config"' in eudr_index_html, (
            "/eudr/index.html must include canopex-ciam-config script element for MSAL"
        )
        ciam_idx = eudr_index_html.index("canopex-ciam-config")
        ciam_context = eudr_index_html[max(0, ciam_idx - 100) : ciam_idx + 100]
        assert 'type="application/json"' in ciam_context, "canopex-ciam-config must be JSON type"

    def test_entrypoints_include_api_audience_placeholder(self, index_html, app_index_html, eudr_index_html):
        """CIAM config placeholders must reserve apiAudience for deploy-time injection."""
        assert '"apiAudience":""' in index_html, "/index.html must include apiAudience in canopex-ciam-config JSON"
        assert '"apiAudience":""' in app_index_html, (
            "/app/index.html must include apiAudience in canopex-ciam-config JSON"
        )
        assert '"apiAudience":""' in eudr_index_html, (
            "/eudr/index.html must include apiAudience in canopex-ciam-config JSON"
        )

    def test_entrypoints_load_canopex_auth_before_consumers(self, index_html, app_index_html, eudr_index_html):
        """canopex-auth.js (shared CIAM module) must load before MSAL consumers.

        landing.js, app-msal.js and any future consumer rely on
        window.CanopexCiam being defined at script execution. Defer scripts
        execute in document order, so canopex-auth.js must appear earlier
        in the HTML than its consumers.
        """
        ciam_script = '<script src="/js/canopex-auth.js" defer></script>'

        # / (marketing landing)
        assert ciam_script in index_html, "/index.html must load canopex-auth.js with defer"
        landing_script = '<script src="/js/landing.js" defer></script>'
        assert index_html.index(ciam_script) < index_html.index(landing_script), (
            "/index.html must load canopex-auth.js before landing.js"
        )

        # /app/
        assert ciam_script in app_index_html, "/app/index.html must load canopex-auth.js with defer"
        app_msal_script = '<script src="/js/app-msal.js" defer></script>'
        assert app_index_html.index(ciam_script) < app_index_html.index(app_msal_script), (
            "/app/index.html must load canopex-auth.js before app-msal.js"
        )

        # /eudr/
        assert ciam_script in eudr_index_html, "/eudr/index.html must load canopex-auth.js with defer"
        assert eudr_index_html.index(ciam_script) < eudr_index_html.index(app_msal_script), (
            "/eudr/index.html must load canopex-auth.js before app-msal.js"
        )

    def test_entrypoints_load_msal_cdn_before_canopex_auth(self, index_html, app_index_html, eudr_index_html):
        """MSAL.js CDN must load before canopex-auth.js (which references window.msal)."""
        ciam_script = "/js/canopex-auth.js"
        msal_marker = "@azure/msal-browser@3.30.0"
        for name, html in (
            ("/index.html", index_html),
            ("/app/index.html", app_index_html),
            ("/eudr/index.html", eudr_index_html),
        ):
            assert msal_marker in html, f"{name} must include MSAL CDN script"
            assert html.index(msal_marker) < html.index(ciam_script), (
                f"{name} must load MSAL CDN before canopex-auth.js"
            )

    def test_app_shell_supports_org_scope_history(self, app_runs_js):
        """EUDR dashboard should request org-scoped analysis history for portfolio triage."""
        assert "scope=' + encodeURIComponent(historyScope)" in app_runs_js, (
            "app-runs.js must include scope parameter when loading analysis history"
        )
        assert "history-org" in app_runs_js, (
            "app-runs.js must keep org history cache separate from user-scoped history cache"
        )

    def test_app_runs_treats_stalled_runs_as_inactive(self, app_runs_js):
        """Stalled runs must not auto-resume indefinitely in history or polling."""
        assert "'stalled'" in app_runs_js, "app-runs.js must treat stalled runtime status as inactive"
        assert "run.customStatus.stalled === true" in app_runs_js, (
            "app-runs.js must treat explicit stalled customStatus as inactive"
        )


# ---------------------------------------------------------------------------
# Quota exhaustion UX — issue #737
# Verify the frontend correctly detects quota_exhausted responses and shows
# an explicit "out of runs" message with an upgrade CTA.
# ---------------------------------------------------------------------------


class TestQuotaExhaustedUx:
    def test_quota_exhausted_detection_requires_explicit_field(self, app_run_lifecycle_js):
        """isQuotaExhaustedError must key off the quota_exhausted field, not message text.

        This prevents false-positive "out of runs" UX for unrelated 403 errors
        (permission denied, member cap, etc.) and guards against message drift.
        """
        assert "quota_exhausted === true" in app_run_lifecycle_js, (
            "app-run-lifecycle.js must detect quota exhaustion via err.body.quota_exhausted "
            "rather than parsing the error message string"
        )

    def test_quota_exhausted_error_function_checks_status_403(self, app_run_lifecycle_js):
        """isQuotaExhaustedError must verify HTTP 403 before flagging quota exhaustion."""
        assert "err.status === 403" in app_run_lifecycle_js, (
            "app-run-lifecycle.js must confirm HTTP 403 before treating an error as quota-exhausted"
        )

    def test_quota_exhausted_shows_out_of_runs_message(self, app_run_lifecycle_js):
        """Quota-exhausted path must surface 'out of runs' copy, not a generic error."""
        assert "You are out of runs" in app_run_lifecycle_js, (
            "app-run-lifecycle.js must display 'You are out of runs' when quota is exhausted"
        )

    def test_quota_exhausted_has_upgrade_cta(self, app_core_dom_js):
        """showQuotaExhaustedStatus must create a visible upgrade CTA button."""
        assert "showQuotaExhaustedStatus" in app_core_dom_js, (
            "app-core-dom.js must expose showQuotaExhaustedStatus for the quota-exhausted UX"
        )
        assert "Upgrade plan" in app_core_dom_js, (
            "app-core-dom.js must create an 'Upgrade plan' CTA button for quota-exhausted state"
        )

    def test_quota_exhausted_cta_calls_on_upgrade_callback(self, app_core_dom_js):
        """The upgrade CTA must invoke the onUpgrade callback so the billing flow opens."""
        assert "onUpgrade" in app_core_dom_js, (
            "app-core-dom.js showQuotaExhaustedStatus must call an onUpgrade callback "
            "so the CTA opens the existing billing flow directly"
        )

    def test_quota_exhausted_wired_to_billing_manage_in_shell(self, app_shell_js):
        """app-shell.js must wire openBillingUpgrade to billingModule.manage."""
        assert "openBillingUpgrade: billingModule.manage" in app_shell_js, (
            "app-shell.js must pass openBillingUpgrade: billingModule.manage to the "
            "run lifecycle module so the upgrade CTA opens the billing portal"
        )

    def test_quota_exhausted_not_triggered_by_other_403(self, app_run_lifecycle_js):
        """Non-quota 403s (permission, member cap) must not show quota-exhausted UX.

        The guard must require BOTH err.status === 403 AND err.body.quota_exhausted === true
        in the same condition, ensuring that a plain permission-denied 403 (which has no
        quota_exhausted field) never triggers the "out of runs" message.
        """
        assert "isQuotaExhaustedError" in app_run_lifecycle_js, (
            "app-run-lifecycle.js must use isQuotaExhaustedError() to isolate quota 403s "
            "from unrelated permission errors"
        )
        # Both conditions must be present in the detection function body so that
        # a bare 403 without quota_exhausted:true (e.g. permission denied, member cap)
        # returns false.
        assert "err.status === 403" in app_run_lifecycle_js, (
            "isQuotaExhaustedError must require HTTP 403 — guards against non-403 errors"
        )
        assert "err.body.quota_exhausted === true" in app_run_lifecycle_js, (
            "isQuotaExhaustedError must require quota_exhausted:true — guards against "
            "unrelated 403s that lack this field (permission denied, member cap, etc.)"
        )

    def test_quota_exhausted_handled_in_token_and_submit_paths(self, app_run_lifecycle_js):
        """Both the upload-token and direct-submit fallback paths must handle quota errors."""
        # isQuotaExhaustedError must be called at least twice: once in the upload-token
        # error handler and once in the direct-submit fallback error handler.
        occurrences = app_run_lifecycle_js.count("isQuotaExhaustedError(")
        assert occurrences >= 2, (
            f"isQuotaExhaustedError must be called in both the upload-token and "
            f"submit-fallback error handlers (found {occurrences} call(s))"
        )


class TestQuotaExhaustedBackendSignal:
    """Backend must emit a machine-readable quota_exhausted field for the frontend contract."""

    def test_error_response_accepts_extra_fields(self):
        """error_response must accept an extra dict that is merged into the JSON body."""
        import inspect

        import blueprints._helpers as helpers_mod

        sig = inspect.signature(helpers_mod.error_response)
        assert "extra" in sig.parameters, (
            "_helpers.error_response must accept an 'extra' keyword argument "
            "so callers can add machine-readable fields (e.g. quota_exhausted: true)"
        )

    def test_submission_quota_exhausted_includes_flag(self):
        """submission.py quota-exhausted 403 must include quota_exhausted in the body."""
        src = (Path(__file__).resolve().parent.parent / "blueprints" / "pipeline" / "submission.py").read_text()
        assert "quota_exhausted" in src, (
            "blueprints/pipeline/submission.py must set quota_exhausted in the 403 "
            "response body for QuotaExhaustedError"
        )

    def test_upload_quota_exhausted_includes_flag(self):
        """upload.py quota-exhausted 403 must include quota_exhausted in the body."""
        src = (Path(__file__).resolve().parent.parent / "blueprints" / "upload.py").read_text()
        assert "quota_exhausted" in src, (
            "blueprints/upload.py must set quota_exhausted in the 403 response body for QuotaExhaustedError"
        )


class TestBillingEmulationUi:
    def test_billing_module_defines_fallback_emulation_tiers(self, app_billing_js):
        """Plan emulation selector should remain usable if API omits emulation.tiers."""
        expected = "['demo', 'free', 'starter', 'pro', 'team', 'enterprise', 'eudr_pro']"
        assert expected in app_billing_js, "app-billing.js must define a fallback tier list for plan emulation"

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

    def test_eudr_subscription_modal_logic_loaded_from_external_script(self, eudr_index_html):
        """EUDR page must load subscription modal logic via external JS (CSP-safe)."""
        assert "/js/app-eudr-subscribe-modal.js" in eudr_index_html, (
            "eudr/index.html must load app-eudr-subscribe-modal.js instead of inline script"
        )
        modal_js = WEBSITE / "js" / "app-eudr-subscribe-modal.js"
        assert modal_js.is_file(), (
            "app-eudr-subscribe-modal.js must exist on disk so the referenced script "
            "does not 404 and break the subscribe modal"
        )
        assert "window.showEudrSubscribeModal" in modal_js.read_text(), (
            "app-eudr-subscribe-modal.js must expose window.showEudrSubscribeModal "
            "for the app shell to call on entitlement failure"
        )

    def test_app_eudr_updates_hero_parcels_and_unavailable_state(self, app_eudr_js):
        """EUDR module should set hero parcel pill and clear loading state on errors."""
        assert "eudr-parcels-used" in app_eudr_js, "app-eudr.js must update the hero parcels stat pill"
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
            "Custom domain must not be hardcoded — it should come from CORS_ALLOWED_ORIGINS env var set by infra"
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

    def test_sitemap_includes_eudr_content_pages(self):
        """EUDR content cluster pages must appear in sitemap.xml for SEO (fixes #617)."""
        sitemap = (WEBSITE / "sitemap.xml").read_text()
        for page in (
            "eudr-supplier-guide.html",
            "eudr-data-sources.html",
            "eudr-faq.html",
            "eudr-glossary.html",
        ):
            assert page in sitemap, f"sitemap.xml must list {page}"

    def test_security_txt_exists(self):
        assert (WEBSITE / ".well-known" / "security.txt").is_file(), ".well-known/security.txt must exist"

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
        assert "data-eudr-app" in content, "eudr/index.html <body> must have data-eudr-app attribute to lock EUDR mode"

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


# One nav model everywhere, so wayfinding doesn't reset page to page (#1256
# follow-up): every page carries the same three core links in the same
# order, and the signed-in identity label is always a link to /account/.
NAV_CORE_LINKS: tuple[tuple[str, str], ...] = (
    ("Due Diligence", "/eudr/"),
    ("Conservation", "/app/"),
    ("Docs", "/docs/"),
)

NAV_PAGES: tuple[Path, ...] = (
    INDEX_HTML,
    EUDR_INDEX_HTML,
    APP_INDEX_HTML,
    ACCOUNT_INDEX_HTML,
    WEBSITE / "docs" / "index.html",
    WEBSITE / "docs" / "eudr-methodology.html",
    WEBSITE / "docs" / "eudr-faq.html",
    WEBSITE / "docs" / "eudr-glossary.html",
    WEBSITE / "docs" / "eudr-data-sources.html",
    WEBSITE / "docs" / "eudr-supplier-guide.html",
    WEBSITE / "docs" / "getting-started.html",
    WEBSITE / "docs" / "kml-guide.html",
    WEBSITE / "docs" / "managing-assessments.html",
    WEBSITE / "docs" / "understanding-evidence.html",
    WEBSITE / "terms.html",
    WEBSITE / "privacy.html",
)


class TestNavigationModel:
    """Every page shares one nav model — see website/README.md."""

    @pytest.mark.parametrize("page_path", NAV_PAGES, ids=lambda p: str(p.relative_to(WEBSITE)))
    def test_core_nav_links_present_in_order(self, page_path):
        html = page_path.read_text()
        positions = []
        for label, href in NAV_CORE_LINKS:
            pattern = rf'<a href="{re.escape(href)}"[^>]*>{re.escape(label)}</a>'
            match = re.search(pattern, html)
            assert match, f"{page_path.name}: missing nav link {label!r} -> {href}"
            positions.append(match.start())
        assert positions == sorted(positions), (
            f"{page_path.name}: nav links must appear in the canonical order {[label for label, _ in NAV_CORE_LINKS]}"
        )

    @pytest.mark.parametrize("page_path", NAV_PAGES, ids=lambda p: str(p.relative_to(WEBSITE)))
    def test_no_same_page_marketing_anchors_in_nav(self, page_path):
        """Nav must not mix in home-page-only anchors like #how-it-works/#faq —
        that's what made the menu look different on every page."""
        html = page_path.read_text()
        nav_html = html.split("</nav>", 1)[0]
        assert "#how-it-works" not in nav_html, f"{page_path.name}: stale #how-it-works nav link"
        assert "#faq" not in nav_html, f"{page_path.name}: stale #faq nav link"

    def test_signed_in_identity_links_to_account(self):
        """Clicking your name/status anywhere must reach /account/ (#1256)."""
        for page_path in (INDEX_HTML, EUDR_INDEX_HTML, APP_INDEX_HTML, ACCOUNT_INDEX_HTML):
            html = page_path.read_text()
            assert '<a class="auth-user" id="auth-user" href="/account/"' in html, (
                f"{page_path.name}: #auth-user must be a real link to /account/, "
                "not an inert span, so signed-in users can always find Account Settings"
            )


class TestQueueAnalysisAuthBypass:
    """ "Confirm & Queue" must work in local dev, not silently no-op (#1263)."""

    def test_queue_analysis_only_redirects_to_login_when_auth_enabled(self, app_run_lifecycle_js):
        assert "_d.authEnabled ? _d.authEnabled() : true" in app_run_lifecycle_js, (
            "queueAnalysis() must check authEnabled() before redirecting to login() — "
            "login() silently no-ops when CIAM isn't configured (local dev), so gating "
            "purely on getAccount() blocks the submit button from ever doing anything"
        )
        assert "if (!currentAccount && authEnabled)" in app_run_lifecycle_js, (
            "queueAnalysis() must only bail out to login() when auth is both disabled-account AND actually enabled"
        )

    def test_run_lifecycle_module_receives_auth_enabled_dep(self, app_shell_js):
        assert "authEnabled: authEnabled," in app_shell_js, (
            "app-shell.js must wire the authEnabled dep into runLifecycleModule.init so queueAnalysis() can check it"
        )


APP_ANALYSIS_PREFLIGHT_JS = WEBSITE / "js" / "app-analysis-preflight.js"
APP_BINDINGS_JS = WEBSITE / "js" / "app-bindings.js"


@pytest.fixture()
def app_analysis_preflight_js():
    return APP_ANALYSIS_PREFLIGHT_JS.read_text()


@pytest.fixture()
def app_bindings_js():
    return APP_BINDINGS_JS.read_text()


class TestKmlToKmzClientCompression:
    """Client-side KML→KMZ compression ensures the pipeline always receives KMZ (#770)."""

    def test_preflight_exports_kmz_helpers(self, app_analysis_preflight_js):
        assert "getPendingKmzBytes" in app_analysis_preflight_js, (
            "app-analysis-preflight.js must export getPendingKmzBytes so the "
            "lifecycle module can read the pending KMZ bytes before upload"
        )
        assert "clearPendingKmzBytes" in app_analysis_preflight_js, (
            "app-analysis-preflight.js must export clearPendingKmzBytes so "
            "bindings can clear stale bytes on manual textarea edits"
        )
        assert "buildKmzFromKmlText" in app_analysis_preflight_js, (
            "app-analysis-preflight.js must define buildKmzFromKmlText to "
            "compress raw KML into a KMZ archive without external libraries"
        )

    def test_preflight_stores_kmz_bytes_for_kml_upload(self, app_analysis_preflight_js):
        assert "_pendingKmzBytes" in app_analysis_preflight_js, (
            "app-analysis-preflight.js must maintain a _pendingKmzBytes state "
            "that loadAnalysisFile populates for the run-lifecycle upload path"
        )
        assert "buildKmzFromKmlText(content)" in app_analysis_preflight_js, (
            "loadAnalysisFile must call buildKmzFromKmlText when a .kml file is loaded"
        )

    def test_preflight_stores_original_bytes_for_kmz_upload(self, app_analysis_preflight_js):
        assert "file.arrayBuffer()" in app_analysis_preflight_js, (
            "loadAnalysisFile must read the original .kmz file as an ArrayBuffer "
            "so original bytes are preserved for upload without re-compression"
        )

    def test_lifecycle_reads_pending_kmz_bytes(self, app_run_lifecycle_js):
        assert "getPendingKmzBytes" in app_run_lifecycle_js, (
            "app-run-lifecycle.js queueAnalysis must call _d.getPendingKmzBytes() "
            "to retrieve file-derived KMZ bytes for blob upload"
        )
        assert "submission.kmz" in app_run_lifecycle_js, (
            "queueAnalysis must send filename: 'submission.kmz' in the token "
            "request body so the backend creates the blob with the correct extension"
        )
        assert "application/vnd.google-earth.kmz" in app_run_lifecycle_js, (
            "queueAnalysis must set Content-Type application/vnd.google-earth.kmz "
            "when uploading KMZ bytes to Azure Blob Storage"
        )

    def test_shell_passes_pending_kmz_dep_to_lifecycle(self, app_shell_js):
        assert "getPendingKmzBytes: preflightModule.getPendingKmzBytes" in app_shell_js, (
            "app-shell.js must wire preflightModule.getPendingKmzBytes into the "
            "runLifecycleModule init deps so queueAnalysis can access KMZ bytes"
        )

    def test_shell_passes_clear_kmz_dep_to_bindings(self, app_shell_js):
        assert "clearPendingKmzBytes: preflightModule.clearPendingKmzBytes" in app_shell_js, (
            "app-shell.js must wire clearPendingKmzBytes into the bindings module "
            "so manual textarea edits clear stale file-derived KMZ bytes"
        )

    def test_bindings_clears_kmz_on_textarea_input(self, app_bindings_js):
        assert "clearPendingKmzBytes" in app_bindings_js, (
            "app-bindings.js must call d.clearPendingKmzBytes() in the KML textarea "
            "input handler so pasted/typed KML doesn't upload stale KMZ bytes"
        )

    def test_preflight_zip_uses_deflate_raw_compression(self, app_analysis_preflight_js):
        assert "deflate-raw" in app_analysis_preflight_js, (
            "buildKmzFromKmlText must use CompressionStream('deflate-raw') "
            "so the resulting KMZ achieves real compression without external libs"
        )

    def test_convert_csv_to_kml_clears_stale_pending_kmz_bytes(self, app_analysis_preflight_js):
        """Assigning textarea.value directly (as convertCSVToKml does) does not
        fire the 'input' event that clears stale bytes elsewhere — without an
        explicit clear here, a previously loaded file's KMZ bytes would be
        uploaded instead of the just-converted CSV-derived KML."""
        convert_fn = app_analysis_preflight_js.split("async function convertCSVToKml", 1)[1]
        convert_fn = convert_fn.split("\n  async function", 1)[0]
        assert "kmlTextarea.value = kmlText;" in convert_fn
        after_assignment = convert_fn.split("kmlTextarea.value = kmlText;", 1)[1]
        assert "_pendingKmzBytes = null;" in after_assignment.split("updateAnalysisPreflight", 1)[0], (
            "convertCSVToKml must clear _pendingKmzBytes after overwriting the "
            "textarea, or a stale file's KMZ bytes could be uploaded instead"
        )

    def test_load_analysis_file_falls_back_when_compression_fails(self, app_analysis_preflight_js):
        """Compression is a wire-size optimisation, not required to load/preview
        a file — if CompressionStream throws (e.g. unsupported browser), the
        file must still load with _pendingKmzBytes left null (raw KML upload
        fallback), not fail the whole load."""
        load_fn = app_analysis_preflight_js.split("async function loadAnalysisFile", 1)[1]
        assert "try {\n          _pendingKmzBytes = await buildKmzFromKmlText(content);" in load_fn, (
            "buildKmzFromKmlText must be called inside its own try/catch so a "
            "compression failure doesn't propagate out and abort the file load"
        )

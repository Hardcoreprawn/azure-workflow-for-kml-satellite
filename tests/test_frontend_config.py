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
APP_SHELL_HTML = WEBSITE / "app" / "index.html"
APP_JS = WEBSITE / "js" / "app.js"
APP_SHELL_JS = WEBSITE / "js" / "app-shell.js"
MSAL_BUNDLE = WEBSITE / "js" / "msal-browser.min.js"
SWA_CONFIG = WEBSITE / "staticwebapp.config.json"
API_CONFIG = WEBSITE / "api-config.json"
HELPERS_PY = Path(__file__).resolve().parent.parent / "blueprints" / "_helpers.py"


@pytest.fixture()
def index_html():
    return INDEX_HTML.read_text()


@pytest.fixture()
def app_js():
    return APP_JS.read_text()


@pytest.fixture()
def app_shell_html():
    return APP_SHELL_HTML.read_text()


@pytest.fixture()
def app_shell_js():
    return APP_SHELL_JS.read_text()


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
    def test_redirect_uri_no_trailing_slash(self, app_js):
        """MSAL redirectUri must use window.location.origin without trailing slash.

        The CIAM app registration has URIs without trailing slash.
        A mismatch causes AADSTS50011.
        """
        assert "window.location.origin + '/'" not in app_js, (
            "redirectUri has trailing slash — will cause AADSTS50011 mismatch with app registration"
        )

    def test_ciam_tenant_configured(self, app_js):
        """CIAM tenant name must be set in app.js."""
        match = re.search(r"CIAM_TENANT_NAME\s*=\s*'(\w+)'", app_js)
        assert match, "CIAM_TENANT_NAME not found in app.js"
        assert match.group(1) != "", "CIAM_TENANT_NAME is empty"

    def test_ciam_client_id_configured(self, app_js):
        """CIAM client ID must be set in app.js."""
        match = re.search(r"CIAM_CLIENT_ID\s*=\s*'([^']+)'", app_js)
        assert match, "CIAM_CLIENT_ID not found in app.js"
        assert len(match.group(1)) > 10, "CIAM_CLIENT_ID looks too short"

    def test_ciam_authority_includes_tenant_path(self, app_js):
        """MSAL authority must point at the tenant-qualified CIAM path.

        Pointing MSAL at the bare ciamlogin.com root breaks OIDC discovery and
        can produce tokens that do not align with backend issuer validation.
        """
        assert ".ciamlogin.com/' + CIAM_TENANT_DOMAIN + '/'" in app_js, (
            "CIAM authority must include the tenant .onmicrosoft.com path"
        )

    def test_known_authority_uses_hostname_only(self, app_js):
        """MSAL knownAuthorities must list the CIAM hostname, not the full authority URL."""
        assert "const CIAM_KNOWN_AUTHORITY = CIAM_TENANT_NAME" in app_js
        assert "? CIAM_TENANT_NAME + '.ciamlogin.com'" in app_js, (
            "knownAuthorities must use the CIAM host name only"
        )


class TestSignInPrompt:
    def test_login_prompt_has_no_replacement_character(self, index_html):
        """The homepage sign-in CTA should not render with a broken replacement glyph."""
        assert "�" not in index_html, (
            "index.html still contains a broken replacement glyph in the sign-in prompt"
        )

    def test_login_prompt_uses_button_control(self, index_html):
        """The inline sign-in CTA should be a real button so it is keyboard accessible."""
        assert (
            '<button type="button" class="login-prompt-link" id="login-prompt-link">' in index_html
        )

    def test_public_demo_limits_are_explicit(self, index_html):
        assert "Public Demo Limits" in index_html
        assert "Max 3 AOIs per run" in index_html
        assert "Max 10,000 hectares per AOI" in index_html

    def test_demo_ai_button_starts_disabled(self, index_html):
        assert 'id="btn-get-ai-insights"' in index_html
        assert "AI Analysis Available on Paid Plans" in index_html
        assert 'disabled aria-disabled="true"' in index_html


class TestSignedInAppShell:
    def test_app_shell_exists(self):
        assert APP_SHELL_HTML.exists(), "website/app/index.html is missing"
        assert APP_SHELL_JS.exists(), "website/js/app-shell.js is missing"

    def test_app_shell_loads_local_msal(self, app_shell_html):
        assert "/js/msal-browser.min.js" in app_shell_html

    def test_root_login_sets_post_login_app_redirect(self, app_js):
        assert "const APP_HOME_PATH = '/app/';" in app_js
        assert "const POST_LOGIN_DESTINATION_KEY = 'treesight-post-login';" in app_js
        assert "window.location.replace(APP_HOME_PATH);" in app_js
        assert "function ciamRedirectOrigin()" in app_js
        assert "function localLoginTransitionUrl()" in app_js
        assert "function consumeLocalLoginRequest()" in app_js
        assert (
            "return runningOnLocalDevOrigin() ? 'http://localhost:4280' : window.location.origin;"
            in app_js
        )
        assert "window.location.replace(localLoginTransitionUrl());" in app_js

    def test_frontend_prefers_id_token_for_identity_only_api_calls(self, app_js, app_shell_js):
        assert (
            "const IDENTITY_ONLY_SCOPES = ['openid', 'profile', 'email', 'offline_access'];"
            in app_js
        )
        assert (
            "const IDENTITY_ONLY_SCOPES = ['openid', 'profile', 'email', 'offline_access'];"
            in app_shell_js
        )
        assert "function selectApiBearerToken(resp)" in app_js
        assert "function selectApiBearerToken(resp)" in app_shell_js
        assert "00000003-0000-0000-c000-000000000000" in app_js
        assert "00000003-0000-0000-c000-000000000000" in app_shell_js

    def test_app_shell_uses_same_post_login_redirect_contract(self, app_shell_js):
        assert "const POST_LOGIN_DESTINATION_KEY = 'treesight-post-login';" in app_shell_js
        assert "sessionStorage.setItem(POST_LOGIN_DESTINATION_KEY, 'app')" in app_shell_js
        assert "function ciamRedirectOrigin()" in app_shell_js
        assert "function localLoginTransitionUrl()" in app_shell_js
        assert "function consumeLocalLoginRequest()" in app_shell_js
        assert (
            "return runningOnLocalDevOrigin() ? 'http://localhost:4280' : window.location.origin;"
            in app_shell_js
        )
        assert "window.location.replace(localLoginTransitionUrl());" in app_shell_js

    def test_app_shell_contains_tier_emulation_controls(self, app_shell_html):
        assert 'id="app-tier-emulation-card"' in app_shell_html
        assert 'id="app-tier-emulation-select"' in app_shell_html
        assert 'id="app-apply-tier-emulation-btn"' in app_shell_html

    def test_app_shell_contains_signed_in_analysis_launcher(self, app_shell_html):
        assert 'id="app-workflow-stage"' in app_shell_html
        assert 'data-focus="run"' in app_shell_html
        assert 'id="app-role-switcher"' in app_shell_html
        assert 'data-role-choice="conservation"' in app_shell_html
        assert 'data-role-choice="eudr"' in app_shell_html
        assert 'data-role-choice="portfolio"' in app_shell_html
        assert 'id="app-preference-switcher"' in app_shell_html
        assert 'data-preference-choice="investigate"' in app_shell_html
        assert 'data-preference-choice="monitor"' in app_shell_html
        assert 'data-preference-choice="report"' in app_shell_html
        assert 'id="app-guided-primary-btn"' in app_shell_html
        assert 'id="app-guided-secondary-btn"' in app_shell_html
        assert 'data-focus-target="history"' in app_shell_html
        assert 'data-focus-target="content"' in app_shell_html
        assert 'id="app-history-card"' in app_shell_html
        assert 'id="app-analysis-card"' in app_shell_html
        assert 'id="app-content-card"' in app_shell_html
        assert 'id="app-history-list"' in app_shell_html
        assert 'id="app-analysis-file"' in app_shell_html
        assert 'id="app-analysis-kml"' in app_shell_html
        assert 'id="app-analysis-lens-title"' in app_shell_html
        assert 'id="app-analysis-preflight"' in app_shell_html
        assert 'id="app-preflight-headline"' in app_shell_html
        assert 'id="app-preflight-features"' in app_shell_html
        assert 'id="app-preflight-aois"' in app_shell_html
        assert 'id="app-preflight-spread"' in app_shell_html
        assert 'id="app-preflight-quota"' in app_shell_html
        assert 'id="app-analysis-submit-btn"' in app_shell_html
        assert 'id="app-analysis-status"' in app_shell_html
        assert 'id="app-analysis-progress"' in app_shell_html
        assert 'id="app-run-detail-grid"' in app_shell_html
        assert 'id="app-run-submitted"' in app_shell_html
        assert 'id="app-run-scope"' in app_shell_html
        assert 'id="app-run-delivery"' in app_shell_html
        assert 'id="app-run-link"' in app_shell_html
        assert 'id="app-run-export-geojson"' in app_shell_html
        assert 'id="app-run-export-csv"' in app_shell_html
        assert 'id="app-run-export-pdf"' in app_shell_html
        assert 'id="app-hero-plan"' in app_shell_html
        assert 'id="app-hero-active-run"' in app_shell_html
        assert 'id="app-history-latest-status"' in app_shell_html
        assert 'id="app-content-imagery"' in app_shell_html
        assert 'id="app-evidence-surface"' in app_shell_html
        assert 'id="app-evidence-map"' in app_shell_html
        assert 'id="app-evidence-ndvi-grid"' in app_shell_html
        assert 'id="app-evidence-weather-grid"' in app_shell_html
        assert 'id="app-evidence-ai-btn"' in app_shell_html
        assert 'id="app-evidence-eudr-btn"' in app_shell_html
        assert 'data-phase="acquisition"' in app_shell_html
        assert 'data-phase="enrichment"' in app_shell_html

    def test_app_shell_calls_billing_emulation_endpoint(self, app_shell_js):
        assert "/api/billing/emulation" in app_shell_js

    def test_app_shell_calls_production_named_analysis_endpoint(self, app_shell_js):
        assert "/api/analysis/submit" in app_shell_js
        assert "/api/analysis/history" in app_shell_js
        assert "/api/export/" in app_shell_js
        assert "function runningOnLocalDevOrigin()" in app_shell_js
        assert "window.location.hostname === '127.0.0.1'" in app_shell_js
        assert "pollAnalysisRun" in app_shell_js
        assert "loadAnalysisHistory" in app_shell_js
        assert "selectAnalysisRun" in app_shell_js
        assert "selectedRunPermalink" in app_shell_js
        assert "downloadRunExport" in app_shell_js
        assert "updateRunDetail" in app_shell_js
        assert "renderAnalysisHistoryList" in app_shell_js
        assert "ANALYSIS_PHASE_DETAILS" in app_shell_js
        assert "const WORKSPACE_ROLES = {" in app_shell_js
        assert "const WORKSPACE_PREFERENCES = {" in app_shell_js
        assert "setAnalysisStep" in app_shell_js
        assert "updateHeroSummary" in app_shell_js
        assert "setHeroRunSummary" in app_shell_js
        assert "setWorkflowFocus" in app_shell_js
        assert "function setWorkspaceRole" in app_shell_js
        assert "function setWorkspacePreference" in app_shell_js
        assert "function buildAnalysisPreflight" in app_shell_js
        assert "function updateAnalysisPreflight" in app_shell_js
        assert "updateHistorySummary" in app_shell_js
        assert "updateContentSummary" in app_shell_js
        assert "loadRunEvidence" in app_shell_js
        assert "/api/timelapse-data/" in app_shell_js
        assert "/api/timelapse-analysis-load/" in app_shell_js
        assert "/api/timelapse-analysis" in app_shell_js
        assert "/api/eudr-assessment" in app_shell_js
        assert "renderEvidenceAnalysis" in app_shell_js
        assert "initEvidenceMap" in app_shell_js

    def test_swa_rewrites_app_route(self, swa_config):
        assert any(
            route.get("route") == "/app" and route.get("rewrite") == "/app/index.html"
            for route in swa_config["routes"]
        ), "staticwebapp.config.json must rewrite /app to the app shell"


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


class TestFirstRunEmptyState:
    """#323 — First-time empty state must surface onboarding instead of a
    blank evidence hero and empty history list."""

    def test_first_run_hero_exists_in_html(self, app_shell_html):
        assert 'id="app-first-run-hero"' in app_shell_html

    def test_first_run_hero_hidden_by_default(self, app_shell_html):
        assert 'id="app-first-run-hero"' in app_shell_html
        # It should be hidden initially (shown only when history is empty)
        assert (
            "hidden" in app_shell_html.split('id="app-first-run-hero"')[0].rsplit("<", 1)[-1]
            or "hidden" in app_shell_html.split('id="app-first-run-hero"')[1].split(">")[0]
        )

    def test_first_run_hero_contains_kml_guide_link(self, app_shell_html):
        # The first-run hero should link to the KML guide for onboarding
        idx = app_shell_html.index('id="app-first-run-hero"')
        # Find the closing tag of this section
        section = app_shell_html[idx : idx + 2000]
        assert "/kml-guide.html" in section

    def test_first_run_hero_contains_cta_button(self, app_shell_html):
        idx = app_shell_html.index('id="app-first-run-hero"')
        section = app_shell_html[idx : idx + 2000]
        assert 'id="app-first-run-cta"' in section

    def test_js_toggles_first_run_layout(self, app_shell_js):
        assert "applyFirstRunLayout" in app_shell_js


class TestEvidenceExportBar:
    """#324 — Export bar promoted into the evidence hero so completed-run
    exports are always one click away."""

    def test_evidence_export_bar_exists(self, app_shell_html):
        assert 'id="app-evidence-export-bar"' in app_shell_html

    def test_evidence_export_bar_inside_evidence_surface(self, app_shell_html):
        surface_idx = app_shell_html.index('id="app-evidence-surface"')
        bar_idx = app_shell_html.index('id="app-evidence-export-bar"')
        assert bar_idx > surface_idx, "Export bar must be inside the evidence surface"

    def test_evidence_export_bar_has_format_buttons(self, app_shell_html):
        idx = app_shell_html.index('id="app-evidence-export-bar"')
        section = app_shell_html[idx : idx + 1000]
        assert 'data-export-format="geojson"' in section
        assert 'data-export-format="csv"' in section
        assert 'data-export-format="pdf"' in section


class TestDemoConversionPrompt:
    """#325 — Post-demo conversion prompt shown after demo timelapse finishes."""

    def test_demo_upsell_exists(self, index_html):
        assert 'id="demo-conversion-prompt"' in index_html

    def test_demo_upsell_hidden_by_default(self, index_html):
        idx = index_html.index('id="demo-conversion-prompt"')
        tag = index_html[:idx].rsplit("<", 1)[-1] + index_html[idx : idx + 200].split(">")[0]
        assert "hidden" in tag

    def test_demo_upsell_links_to_pricing(self, index_html):
        idx = index_html.index('id="demo-conversion-prompt"')
        section = index_html[idx : idx + 1500]
        assert "#pricing" in section

    def test_demo_upsell_has_dismiss(self, index_html):
        idx = index_html.index('id="demo-conversion-prompt"')
        section = index_html[idx : idx + 1500]
        assert 'id="demo-conversion-dismiss"' in section

    def test_js_shows_conversion_prompt_after_timelapse(self, app_js):
        assert "demo-conversion-prompt" in app_js


class TestDemoBoundaries:
    def test_demo_js_has_explicit_polygon_cap(self, app_js):
        assert "const DEMO_MAX_POLYGONS = 3;" in app_js
        assert "checkDemoBounds(polygons)" in app_js

    def test_demo_js_has_explicit_area_cap(self, app_js):
        assert "const DEMO_MAX_AREA_HA = 10000;" in app_js
        assert "function polygonAreaHa(coords)" in app_js

    def test_demo_js_gates_ai_by_plan_capabilities(self, app_js):
        assert "function updateDemoAiControls(data)" in app_js
        assert "data.capabilities.ai_insights" in app_js

    def test_demo_js_prefers_same_origin_proxy_for_local_dev(self, app_js):
        assert "function runningOnLocalDevOrigin()" in app_js
        assert "window.location.hostname === '127.0.0.1'" in app_js
        assert "var localRes = await fetch('/api/health');" in app_js

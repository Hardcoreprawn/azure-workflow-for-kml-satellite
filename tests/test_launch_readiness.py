"""Launch-readiness regression tests.

These tests ensure that the hardening fixes for public launch are not
accidentally removed or misconfigured.  They cover:

1. Container Apps scaling limits (maxReplicas)
2. App Insights browser analytics on all pages
3. Rate limiting on demo-submit endpoint
4. REQUIRE_AUTH wired into production app settings
5. Log Analytics daily ingestion cap
6. detect-secrets in CI security workflow
7. App Insights availability test (URL ping)
8. CSP allows App Insights SDK
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
WEBSITE = ROOT / "website"
INFRA = ROOT / "infra" / "tofu"
MAIN_TF = INFRA / "main.tf"
VARIABLES_TF = INFRA / "variables.tf"
SECURITY_YML = ROOT / ".github" / "workflows" / "security.yml"
DEPLOY_YML = ROOT / ".github" / "workflows" / "deploy.yml"
SWA_CONFIG = WEBSITE / "staticwebapp.config.json"

HTML_PAGES = [
    WEBSITE / "index.html",
    WEBSITE / "docs" / "index.html",
    WEBSITE / "docs" / "kml-guide.html",
    WEBSITE / "privacy.html",
    WEBSITE / "terms.html",
    WEBSITE / "docs" / "eudr-methodology.html",
]


# ---------------------------------------------------------------------------
# 1. Container Apps scaling limits
# ---------------------------------------------------------------------------


class TestContainerAppsScaling:
    """Ensure the Function App has a maximum instance cap to prevent runaway costs."""

    @pytest.fixture()
    def main_tf(self):
        return MAIN_TF.read_text()

    @pytest.fixture()
    def variables_tf(self):
        return VARIABLES_TF.read_text()

    def test_function_app_config_has_max_instance_count(self, main_tf):
        assert "maximumInstanceCount" in main_tf, (
            "main.tf must set maximumInstanceCount in functionAppConfig "
            "to cap Container Apps scaling"
        )

    def test_max_instances_variable_exists(self, variables_tf):
        assert "function_max_instances" in variables_tf, (
            "variables.tf must define function_max_instances variable"
        )

    def test_max_instances_default_is_reasonable(self, variables_tf):
        match = re.search(
            r'variable\s+"function_max_instances".*?default\s*=\s*(\d+)',
            variables_tf,
            re.DOTALL,
        )
        assert match, "function_max_instances variable must have a default"
        default = int(match.group(1))
        assert 1 <= default <= 10, (
            f"function_max_instances default is {default} — "
            "should be between 1 and 10 for cost safety"
        )


# ---------------------------------------------------------------------------
# 2. App Insights browser analytics
# ---------------------------------------------------------------------------


class TestBrowserAnalytics:
    """Ensure every public HTML page loads the analytics script."""

    @pytest.mark.parametrize("page", HTML_PAGES, ids=lambda p: p.name)
    def test_analytics_script_tag_present(self, page):
        content = page.read_text()
        assert "/js/analytics.js" in content, (
            f'{page.name} must include <script src="/js/analytics.js"> '
            "for App Insights browser telemetry"
        )

    @pytest.mark.parametrize("page", HTML_PAGES, ids=lambda p: p.name)
    def test_ai_connection_string_meta_tag(self, page):
        content = page.read_text()
        assert 'name="ai-connection-string"' in content, (
            f'{page.name} must include <meta name="ai-connection-string"> '
            "for the analytics SDK to read at runtime"
        )

    def test_analytics_js_exists(self):
        js = WEBSITE / "js" / "analytics.js"
        assert js.exists(), "website/js/analytics.js must exist"
        content = js.read_text()
        assert "trackPageView" in content, (
            "analytics.js must call trackPageView for page-level telemetry"
        )

    def test_analytics_disables_cookies(self):
        """GDPR: analytics must not set cookies."""
        content = (WEBSITE / "js" / "analytics.js").read_text()
        assert "disableCookiesUsage" in content, (
            "analytics.js must set disableCookiesUsage for GDPR compliance"
        )


# ---------------------------------------------------------------------------
# 3. Rate limiter on demo-submit
# ---------------------------------------------------------------------------


class TestDemoSubmitRateLimiter:
    """Ensure the demo-submit endpoint has rate limiting to prevent abuse."""

    def test_demo_submit_imports_pipeline_limiter(self):
        src = (ROOT / "blueprints" / "demo.py").read_text()
        assert "pipeline_limiter" in src, (
            "demo.py must import pipeline_limiter to rate-limit demo-submit"
        )

    def test_demo_submit_calls_rate_limiter(self):
        src = (ROOT / "blueprints" / "demo.py").read_text()
        # Find the demo_submit function and check it uses the limiter
        func_match = re.search(
            r"def demo_submit\(.*?\n(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        assert func_match, "demo_submit function not found"
        body = func_match.group(1)
        assert "pipeline_limiter.is_allowed" in body, (
            "demo_submit must call pipeline_limiter.is_allowed() before processing the request"
        )

    def test_rate_limit_returns_429(self):
        """Rate-limited requests must get a 429 response."""
        src = (ROOT / "blueprints" / "demo.py").read_text()
        func_match = re.search(
            r"def demo_submit\(.*?\n(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        assert func_match
        body = func_match.group(1)
        assert "429" in body, "demo_submit must return HTTP 429 when rate limited"


# ---------------------------------------------------------------------------
# 4. REQUIRE_AUTH in production
# ---------------------------------------------------------------------------


class TestRequireAuth:
    """Ensure REQUIRE_AUTH is wired into the Function App for production."""

    def test_require_auth_in_app_settings(self):
        tf = MAIN_TF.read_text()
        assert "REQUIRE_AUTH" in tf, (
            "main.tf must include REQUIRE_AUTH in appSettings "
            "to prevent silent anonymous fallback in production"
        )

    def test_require_auth_conditional_on_environment(self):
        tf = MAIN_TF.read_text()
        # The name and value are on separate lines in HCL
        match = re.search(
            r'name\s*=\s*"REQUIRE_AUTH"\s*\n\s*value\s*=\s*(.+)',
            tf,
        )
        assert match, "REQUIRE_AUTH app setting not found"
        value_expr = match.group(1)
        assert "prd" in value_expr, (
            "REQUIRE_AUTH should be enabled for production (prd) environment"
        )


# ---------------------------------------------------------------------------
# 5. Log Analytics daily cap
# ---------------------------------------------------------------------------


class TestLogAnalyticsCap:
    """Ensure Log Analytics has a daily ingestion cap to prevent cost surprises."""

    def test_daily_quota_gb_in_workspace(self):
        tf = MAIN_TF.read_text()
        assert "daily_quota_gb" in tf, (
            "main.tf must set daily_quota_gb on the Log Analytics workspace to cap ingestion costs"
        )

    def test_log_daily_cap_variable_exists(self):
        tf = VARIABLES_TF.read_text()
        assert "log_daily_cap_gb" in tf, "variables.tf must define log_daily_cap_gb variable"


# ---------------------------------------------------------------------------
# 6. detect-secrets in CI
# ---------------------------------------------------------------------------


class TestDetectSecretsCi:
    """Ensure detect-secrets runs in CI, not just as a pre-commit hook."""

    def test_security_workflow_has_detect_secrets(self):
        yml = SECURITY_YML.read_text()
        assert "detect-secrets" in yml, (
            "security.yml must include a detect-secrets job — "
            "pre-commit hooks can be bypassed with --no-verify"
        )

    def test_detect_secrets_is_a_job(self):
        yml = SECURITY_YML.read_text()
        assert re.search(r"^\s+detect-secrets:", yml, re.MULTILINE), (
            "detect-secrets must be a named job in security.yml"
        )

    def test_detect_secrets_uses_committed_baseline(self):
        yml = SECURITY_YML.read_text()
        assert "--baseline" in yml, (
            "detect-secrets CI must use a committed .secrets.baseline "
            "so new secrets are caught (not a fresh baseline each run)"
        )

    def test_secrets_baseline_file_exists(self):
        baseline = ROOT / ".secrets.baseline"
        assert baseline.exists(), (
            ".secrets.baseline must be committed for the detect-secrets CI job"
        )


# ---------------------------------------------------------------------------
# 7. App Insights availability test
# ---------------------------------------------------------------------------


class TestAvailabilityTest:
    """Ensure an availability/ping test monitors site uptime."""

    def test_web_test_resource_exists(self):
        tf = MAIN_TF.read_text()
        assert "application_insights_standard_web_test" in tf, (
            "main.tf must include an Application Insights web test for uptime monitoring"
        )

    def test_web_test_has_geo_locations(self):
        tf = MAIN_TF.read_text()
        assert "geo_locations" in tf, "The web test must ping from multiple geographic locations"


# ---------------------------------------------------------------------------
# 8. CSP allows App Insights SDK
# ---------------------------------------------------------------------------


class TestCspAppInsights:
    """Ensure CSP permits the App Insights JavaScript SDK and telemetry endpoint."""

    @pytest.fixture()
    def csp(self):
        config = json.loads(SWA_CONFIG.read_text())
        return config["globalHeaders"]["Content-Security-Policy"]

    def test_script_src_allows_monitor_cdn(self, csp):
        script_match = re.search(r"script-src\s+([^;]+)", csp)
        assert script_match, "CSP missing script-src"
        assert "js.monitor.azure.com" in script_match.group(1), (
            "CSP script-src must allow js.monitor.azure.com for the App Insights SDK"
        )

    def test_connect_src_allows_telemetry_endpoint(self, csp):
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src"
        connect_src = connect_match.group(1)
        assert (
            "applicationinsights.azure.com" in connect_src or "visualstudio.com" in connect_src
        ), "CSP connect-src must allow App Insights telemetry ingestion endpoint"


# ---------------------------------------------------------------------------
# 9. Deploy workflow applies CLI-managed settings
# ---------------------------------------------------------------------------


class TestDeployWorkflowSettings:
    """Ensure the deploy workflow applies settings that bypass tofu ignore_changes."""

    @pytest.fixture()
    def deploy_yml(self):
        return DEPLOY_YML.read_text()

    def test_deploy_sets_require_auth_via_cli(self, deploy_yml):
        assert "REQUIRE_AUTH" in deploy_yml, (
            "deploy.yml must set REQUIRE_AUTH via az CLI because body is ignore_changes in tofu"
        )

    def test_deploy_sets_max_instances_via_cli(self, deploy_yml):
        assert "maximumInstanceCount" in deploy_yml, (
            "deploy.yml must apply maximumInstanceCount via az CLI because "
            "body is ignore_changes in tofu"
        )

    def test_deploy_injects_analytics_connection_string(self, deploy_yml):
        assert "ai-connection-string" in deploy_yml, (
            "deploy.yml must inject the App Insights connection string into "
            "HTML meta tags before SWA upload"
        )

    def test_appinsights_connection_string_output_exists(self):
        tf = (INFRA / "outputs.tf").read_text()
        assert "appinsights_connection_string" in tf, (
            "outputs.tf must export appinsights_connection_string for the "
            "deploy workflow to inject into the static site"
        )


# ---------------------------------------------------------------------------
# 10. Event Grid webhook wiring must match runtime function index
# ---------------------------------------------------------------------------


class TestEventGridWebhookWiring:
    """Ensure Event Grid subscription targets the indexed function name with auth key."""

    def test_event_grid_webhook_uses_blob_trigger_name(self):
        tf = MAIN_TF.read_text()
        assert "functionName=blob_trigger" in tf, (
            "Event Grid subscription endpointUrl must target functionName=blob_trigger "
            "to match the indexed Event Grid trigger function"
        )

    def test_event_grid_webhook_includes_code_query_param(self):
        tf = MAIN_TF.read_text()
        assert "&code=${local.eventgrid_key}" in tf, (
            "Event Grid webhook endpointUrl must include the system key query param"
        )

"""Launch-readiness regression tests.

These tests ensure that the hardening fixes for public launch are not
accidentally removed or misconfigured.  They cover:

1. Container Apps scaling limits (maxReplicas)
2. App Insights browser analytics on all pages
3. Auth enforcement on pipeline submission endpoint
4. REQUIRE_AUTH unconditionally enabled for all deployed environments
5. Log Analytics daily ingestion cap
6. detect-secrets in CI security workflow
7. App Insights availability test (URL ping)
8. CSP allows App Insights SDK
9. Deploy workflow settings (sensitive outputs)
10. Event Grid wiring (trigger name and webhook key)
11. Trivy signal quality and exception discipline
12. (removed — CIAM replaced with SWA pre-configured providers in #495)
13. Bearer-only CIAM auth (single path, no legacy fallbacks)
"""

from __future__ import annotations

import json
import re
import typing
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml

from treesight.security.url import csp_token_matches_host as _csp_token_matches_host

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
WEBSITE = ROOT / "website"
INFRA = ROOT / "infra" / "tofu"
MAIN_TF = INFRA / "main.tf"
VARIABLES_TF = INFRA / "variables.tf"
DEV_TFVARS = INFRA / "environments" / "dev.tfvars"
HOST_JSON = ROOT / "host.json"
SECURITY_YML = ROOT / ".github" / "workflows" / "security.yml"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
CI_DOCS_STUB_YML = ROOT / ".github" / "workflows" / "ci-docs-stub.yml"
CODEQL_YML = ROOT / ".github" / "workflows" / "codeql.yml"
ACTIONLINT_YML = ROOT / ".github" / "workflows" / "actionlint.yml"
DEPLOY_YML = ROOT / ".github" / "workflows" / "deploy.yml"
BASE_IMAGE_YML = ROOT / ".github" / "workflows" / "base-image.yml"
INFRACOST_YML = ROOT / ".github" / "workflows" / "infracost.yml"
REQUIRE_LINKED_ISSUE_YML = ROOT / ".github" / "workflows" / "require-linked-issue.yml"
PREVIEW_SITE_YML = ROOT / ".github" / "workflows" / "preview-site.yml"
INFRACOST_USAGE = INFRA / "infracost-usage.yml"
TRIVY_IGNORE = ROOT / ".trivyignore"
MAKEFILE = ROOT / "Makefile"
COMPOSE_YML = ROOT / "docker-compose.yml"
DEPENDABOT_YML = ROOT / ".github" / "dependabot.yml"
TRIVY_SCAN_ACTION = ROOT / ".github" / "actions" / "trivy-scan" / "action.yml"
SWA_CONFIG = WEBSITE / "staticwebapp.config.json"
API_INTERFACE_REFERENCE = ROOT / "docs" / "API_INTERFACE_REFERENCE.md"
OPENAPI_YAML = ROOT / "docs" / "openapi.yaml"
PULL_REQUEST_TEMPLATE = ROOT / ".github" / "pull_request_template.md"

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
# 3. Submission auth enforcement
# ---------------------------------------------------------------------------


class TestSubmissionAuthRequirement:
    """Ensure pipeline execution cannot proceed anonymously."""

    def test_submission_imports_auth_check(self):
        src = (ROOT / "blueprints" / "pipeline" / "submission.py").read_text()
        assert "check_auth" in src, (
            "submission.py must import check_auth so pipeline submission requires sign-in"
        )

    def test_analysis_submit_routes_to_signed_in_handler(self):
        src = (ROOT / "blueprints" / "pipeline" / "submission.py").read_text()
        func_match = re.search(
            r"def analysis_submit\(.*?\n(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        assert func_match, "analysis_submit function not found"
        body = func_match.group(1)
        assert "_submit_analysis_request" in body, (
            "analysis_submit must delegate to the signed-in submission handler"
        )

    def test_no_anonymous_submit_handler_remains(self):
        src = (ROOT / "blueprints" / "pipeline" / "submission.py").read_text()
        assert "_submit_demo_request" not in src, (
            "submission.py must not keep an anonymous pipeline submission path"
        )


# ---------------------------------------------------------------------------
# 4. REQUIRE_AUTH in all deployed environments
# ---------------------------------------------------------------------------


class TestRequireAuth:
    """Ensure REQUIRE_AUTH is unconditionally enabled for all deployed environments."""

    def test_require_auth_in_app_settings(self):
        tf = MAIN_TF.read_text()
        assert "REQUIRE_AUTH" in tf, (
            "main.tf must include REQUIRE_AUTH in appSettings "
            "to prevent silent anonymous fallback in deployed environments"
        )

    def test_require_auth_unconditional(self):
        """REQUIRE_AUTH must be 'true' unconditionally — no per-env conditional."""
        tf = MAIN_TF.read_text()
        match = re.search(
            r"REQUIRE_AUTH\s*=\s*(.+)",
            tf,
        )
        assert match, "REQUIRE_AUTH app setting not found"
        value_expr = match.group(1).strip()
        assert value_expr == '"true"', (
            f"REQUIRE_AUTH must be unconditionally '\"true\"', got: {value_expr}"
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

    def test_dev_daily_cap_is_tight(self):
        tfvars = DEV_TFVARS.read_text()
        match = re.search(r"log_daily_cap_gb\s*=\s*([0-9.]+)", tfvars)
        assert match, "dev.tfvars must set log_daily_cap_gb explicitly"
        daily_cap_gb = float(match.group(1))
        assert daily_cap_gb <= 0.1, (
            f"dev log_daily_cap_gb is {daily_cap_gb} — keep it at 0.1 GB/day or lower "
            "until Log Analytics proves its value"
        )

    def test_dev_custom_domain_is_set(self):
        tfvars = DEV_TFVARS.read_text()
        match = re.search(r'^custom_domain\s*=\s*"([^"]*)"', tfvars, re.MULTILINE)
        assert match, "dev.tfvars must set custom_domain explicitly"
        assert match.group(1) != "", (
            "dev.tfvars must set custom_domain to the apex domain "
            "so the SWA serves CORS headers for the correct origin"
        )


# ---------------------------------------------------------------------------
# 5a. Static Web App cost controls
# ---------------------------------------------------------------------------


class TestStaticWebAppCostControls:
    """Ensure the Static Web App SKU stays on Free tier."""

    @staticmethod
    def _static_web_app_main_body(tf: str) -> str:
        match = re.search(
            r'resource\s+"azurerm_static_web_app"\s+"main"\s*\{(?P<body>.*?)\n\}',
            tf,
            re.DOTALL,
        )
        assert match, "main.tf must define azurerm_static_web_app.main"
        return match.group("body")

    def test_static_web_app_sku_tier_is_free(self):
        body = self._static_web_app_main_body(MAIN_TF.read_text())
        assert 'sku_tier = "Free"' in body, (
            'azurerm_static_web_app.main must keep sku_tier="Free" '
            "to preserve the agreed SWA cost reduction"
        )

    def test_static_web_app_sku_size_is_free(self):
        body = self._static_web_app_main_body(MAIN_TF.read_text())
        assert 'sku_size = "Free"' in body, (
            'azurerm_static_web_app.main must keep sku_size="Free" '
            "to preserve the agreed SWA cost reduction"
        )


# ---------------------------------------------------------------------------
# 5a-2. Preview-site workflow graceful degradation
# ---------------------------------------------------------------------------


class TestPreviewSiteGracefulDegradation:
    """Ensure Deploy Preview cannot block merges when the SWA token is missing/invalid.

    The deploy step must be guarded by a token-presence check so that an absent
    or expired SWA_DEPLOYMENT_TOKEN causes a warning rather than a job failure.
    """

    @pytest.fixture()
    def deploy_steps(self) -> list[dict]:
        """Return the steps list from the deploy-preview job."""
        workflow = yaml.safe_load(PREVIEW_SITE_YML.read_text())
        return workflow["jobs"]["deploy-preview"]["steps"]

    def _find_step(
        self, steps: list[dict], step_id: str | None = None, name_fragment: str | None = None
    ) -> dict | None:
        for step in steps:
            if step_id and step.get("id") == step_id:
                return step
            if name_fragment and name_fragment.lower() in (step.get("name") or "").lower():
                return step
        return None

    def test_token_check_step_exists_and_sets_output(self, deploy_steps):
        step = self._find_step(deploy_steps, step_id="check-token")
        assert step is not None, (
            "preview-site.yml deploy-preview job must contain a step with "
            "id: check-token that probes SWA_DEPLOYMENT_TOKEN availability"
        )
        run_script = step.get("run", "")
        assert "GITHUB_OUTPUT" in run_script, (
            "check-token step must write 'available' to GITHUB_OUTPUT"
        )
        assert "available=false" in run_script or "available=true" in run_script, (
            "check-token step must emit an 'available' output so downstream "
            "steps can conditionally skip the deploy"
        )

    def test_deploy_step_gated_on_token_check(self, deploy_steps):
        step = self._find_step(deploy_steps, name_fragment="Deploy to SWA")
        assert step is not None, (
            "preview-site.yml must contain a 'Deploy to SWA staging environment' step"
        )
        condition = step.get("if", "")
        assert "steps.check-token.outputs.available" in condition, (
            "The 'Deploy to SWA staging environment' step must be gated on "
            "steps.check-token.outputs.available so it skips when the token is absent"
        )

    def test_deploy_step_has_continue_on_error(self, deploy_steps):
        step = self._find_step(deploy_steps, name_fragment="Deploy to SWA")
        assert step is not None, (
            "preview-site.yml must contain a 'Deploy to SWA staging environment' step"
        )
        assert step.get("continue-on-error") is True, (
            "The 'Deploy to SWA staging environment' step must set "
            "continue-on-error: true so an invalid/expired token does not fail the "
            "job and block the PR"
        )


# ---------------------------------------------------------------------------
# 5b. Host logging cost controls
# ---------------------------------------------------------------------------


class TestHostLoggingCostControls:
    """Ensure low-value host/runtime telemetry is aggressively reduced."""

    @pytest.fixture()
    def host_config(self):
        return json.loads(HOST_JSON.read_text())

    def test_default_log_level_is_warning(self, host_config):
        levels = host_config["logging"]["logLevel"]
        assert levels["default"] == "Warning", (
            "host.json should default runtime logging to Warning to reduce console log ingest"
        )

    def test_durable_task_logs_are_information(self, host_config):
        levels = host_config["logging"]["logLevel"]
        assert levels["Host.Triggers.DurableTask"] == "Information", (
            "DurableTask must be at Information level so activity scheduling "
            "events appear in Log Analytics for pipeline debugging"
        )

    def test_sampling_keeps_exceptions_unsampled(self, host_config):
        sampling = host_config["logging"]["applicationInsights"]["samplingSettings"]
        assert sampling["isEnabled"] is True
        assert sampling["excludedTypes"] == "Exception", (
            "App Insights sampling should preserve exceptions, not every request"
        )


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
        assert "geo_locations" in tf, "The web test must specify at least one geographic location"


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
        sources = script_match.group(1).split()
        assert any(_csp_token_matches_host(src, "js.monitor.azure.com") for src in sources), (
            "CSP script-src must allow js.monitor.azure.com for the App Insights SDK"
        )

    def test_connect_src_allows_telemetry_endpoint(self, csp):
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src"
        sources = connect_match.group(1).split()
        assert any(
            _csp_token_matches_host(src, "applicationinsights.azure.com")
            or _csp_token_matches_host(src, "visualstudio.com")
            for src in sources
        ), "CSP connect-src must allow App Insights telemetry ingestion endpoint"

    def test_connect_src_allows_monitor_config(self, csp):
        """Azure Monitor SDK fetches config from js.monitor.azure.com at runtime."""
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src"
        sources = connect_match.group(1).split()
        assert any(_csp_token_matches_host(src, "js.monitor.azure.com") for src in sources), (
            "CSP connect-src must allow js.monitor.azure.com for App Insights config fetch"
        )

    def test_no_inline_event_handlers_in_app_html(self):
        """CSP without unsafe-inline in script-src blocks onclick= handlers."""
        html = (ROOT / "website" / "app" / "index.html").read_text()
        inline_pattern = re.compile(r'\bon\w+\s*=\s*["\']', re.IGNORECASE)
        matches = inline_pattern.findall(html)
        assert not matches, (
            f"Found inline event handler(s) in app/index.html that CSP will block: {matches}"
        )

    def test_no_inline_executable_scripts_in_eudr_html(self):
        """CSP without unsafe-inline in script-src blocks inline executable scripts."""
        html = (ROOT / "website" / "eudr" / "index.html").read_text()

        class _InlineScriptParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.disallowed_inline = []
                self._disallowed_candidate = False
                self._candidate_has_code = False
                self._candidate_attrs = "<script>"

            def handle_starttag(self, tag, attrs):
                if tag.lower() != "script":
                    return
                attr_map = {
                    (name or "").lower(): (value or "").strip().lower() for name, value in attrs
                }
                has_src = bool(attr_map.get("src"))
                is_json_data_tag = attr_map.get("type") == "application/json"
                self._disallowed_candidate = not has_src and not is_json_data_tag
                self._candidate_has_code = False
                attrs_text = " ".join(
                    f'{name}="{value}"' if value is not None else str(name) for name, value in attrs
                ).strip()
                self._candidate_attrs = (
                    f"<script {attrs_text}>".strip() if attrs_text else "<script>"
                )

            def handle_data(self, data):
                if self._disallowed_candidate and data.strip():
                    self._candidate_has_code = True

            def handle_endtag(self, tag):
                if tag.lower() != "script":
                    return
                if self._disallowed_candidate and self._candidate_has_code:
                    self.disallowed_inline.append(self._candidate_attrs)
                self._disallowed_candidate = False
                self._candidate_has_code = False

        parser = _InlineScriptParser()
        parser.feed(html)

        assert not parser.disallowed_inline, (
            "Found inline executable <script> blocks in eudr/index.html that CSP will block: "
            f"{parser.disallowed_inline}"
        )

    def test_connect_src_covers_cdn_domains_for_source_maps(self, csp):
        """CDN domains in script-src/style-src must also appear in connect-src.

        Browsers fetch source maps (e.g. leaflet.js.map) via connect-src.
        If a CDN is trusted for scripts but missing from connect-src, the
        source-map fetch is blocked — polluting DevTools with CSP errors.
        """
        skip = {"'self'", "'unsafe-inline'", "'none'"}
        connect_match = re.search(r"connect-src\s+([^;]+)", csp)
        assert connect_match, "CSP missing connect-src"
        connect_sources = connect_match.group(1).split()

        for directive in ("script-src", "style-src"):
            dir_match = re.search(rf"{directive}\s+([^;]+)", csp)
            if not dir_match:
                continue
            for src in dir_match.group(1).split():
                if src in skip or not src.startswith("https://"):
                    continue
                host = src.split("//", 1)[1].rstrip("/")
                assert any(_csp_token_matches_host(cs, host) for cs in connect_sources), (
                    f"CSP {directive} allows {src} but connect-src does not — "
                    f"source-map fetches will be blocked"
                )


# ---------------------------------------------------------------------------
# 9. Deploy workflow applies CLI-managed settings
# ---------------------------------------------------------------------------


class TestDeployWorkflowSettings:
    """Ensure the deploy workflow applies settings that bypass tofu ignore_changes."""

    @pytest.fixture()
    def deploy_yml(self):
        return DEPLOY_YML.read_text()

    def test_deploy_sets_app_settings_via_cli(self, deploy_yml):
        assert "az webapp config appsettings set" in deploy_yml, (
            "deploy.yml must still apply Function App settings via az CLI while "
            "body is ignore_changes in tofu"
        )

    def test_deploy_sets_max_instances_via_cli(self, deploy_yml):
        assert "maximumInstanceCount" in deploy_yml, (
            "deploy.yml must apply maximumInstanceCount via az CLI because "
            "body is ignore_changes in tofu"
        )

    def test_deploy_updates_container_app_scale_rules_via_patch(self, deploy_yml):
        patch_call = (
            "az rest --method PATCH \\\n"
            '              --url "${CONTAINER_APP_ID}?api-version=2024-03-01"'
        )
        assert patch_call in deploy_yml, (
            "deploy.yml must use PATCH (not PUT) when wiring KEDA scale rules"
            " on the backing Container App"
        )
        assert "az rest --method PUT" not in deploy_yml, (
            "deploy.yml must not replace the entire Container App resource"
            " when updating scale rules"
        )

    def test_deploy_sources_cli_managed_function_settings_from_tofu_outputs(self, deploy_yml):
        assert "tofu output -json function_app_cli_app_settings" in deploy_yml, (
            "deploy.yml must source CLI-managed Function App app settings from tofu outputs "
            "to avoid drifting away from Terraform"
        )
        assert "tofu output -raw function_app_cli_maximum_instance_count" in deploy_yml, (
            "deploy.yml must source the CLI-managed scale cap from tofu outputs "
            "to avoid reparsing tfvars"
        )
        assert "grep 'ciam_tenant_name' environments/dev.tfvars" not in deploy_yml, (
            "deploy.yml should not reference CIAM settings (removed in #495)"
        )

    def test_deploy_injects_analytics_connection_string(self, deploy_yml):
        assert "ai-connection-string" in deploy_yml, (
            "deploy.yml must inject the App Insights connection string into "
            "HTML meta tags before SWA upload"
        )

    def test_swa_app_settings_not_managed_by_cli(self, deploy_yml):
        assert "az staticwebapp appsettings set" not in deploy_yml, (
            "deploy.yml must NOT configure SWA app settings via CLI"
        )

    def test_deploy_smoke_checks_container_apps_fa(self, deploy_yml):
        """Deploy must smoke-check the Container Apps FA health endpoint."""
        assert "Smoke-check Container Apps Function App" in deploy_yml, (
            "deploy.yml must have a named smoke check step targeting Container Apps FA"
        )
        assert "function_app_orch_hostname" in deploy_yml, (
            "deploy.yml smoke check must use explicit orchestrator hostname output"
        )
        assert (
            '"apiBase": "https://${{ needs.deploy-infra.outputs.function_app_orch_hostname }}"'
            in deploy_yml
        ), "deploy.yml api-config injection must source orchestrator hostname output"
        assert (
            'FA_HOSTNAME="${{ needs.deploy-infra.outputs.function_app_orch_hostname }}"'
            in deploy_yml
        ), "deploy.yml smoke-check step must target orchestrator hostname output"
        assert "/api/health" in deploy_yml, (
            "deploy.yml smoke check must test /api/health on the Container Apps FA"
        )
        assert "curl" in deploy_yml, "deploy.yml smoke check must curl the FA health endpoint"

    def test_verify_runtime_readiness_checks_both_function_apps(self, deploy_yml):
        assert "COMPUTE_HOSTNAME=$(tofu output -raw function_app_default_hostname)" in deploy_yml, (
            "deploy.yml readiness verification must check compute app hostname"
        )
        assert (
            "ORCH_HOSTNAME=$(tofu output -raw function_app_orch_default_hostname)" in deploy_yml
        ), "deploy.yml readiness verification must check orchestrator app hostname"
        assert 'verify_host_readiness "compute" "$COMPUTE_HOSTNAME"' in deploy_yml, (
            "deploy.yml readiness verification must probe compute app health/readiness"
        )
        assert 'verify_host_readiness "orchestrator" "$ORCH_HOSTNAME"' in deploy_yml, (
            "deploy.yml readiness verification must probe orchestrator app health/readiness"
        )

    def test_rollback_restores_both_function_apps(self, deploy_yml):
        assert "steps.configure-orch-app.outcome == 'success'" in deploy_yml, (
            "rollback guard must consider orchestrator configure step outcome"
        )
        assert "steps.current-image.outputs.image_compute" in deploy_yml, (
            "rollback guard must use captured compute image output"
        )
        assert "steps.current-image.outputs.image_orch" in deploy_yml, (
            "rollback guard must use captured orchestrator image output"
        )
        assert 'ORCH_NAME="${{ steps.current-image.outputs.orch_name }}"' in deploy_yml, (
            "rollback step must restore orchestrator app image"
        )
        assert "steps.compute-hostname.outputs.hostname" in deploy_yml, (
            "rollback step must validate compute app health after rollback"
        )

    def test_workflow_dispatch_supports_manual_teardown_rebuild(self, deploy_yml):
        assert "rebuild_after_manual_teardown" in deploy_yml, (
            "deploy.yml manual dispatch must allow rebuilding dev after a manual teardown"
        )

    def test_workflow_dispatch_supports_async_smoke_tuning(self, deploy_yml):
        assert "smoke_poll_interval_seconds" in deploy_yml, (
            "deploy.yml workflow_dispatch must expose smoke poll interval control"
        )
        assert "smoke_max_attempts" in deploy_yml, (
            "deploy.yml workflow_dispatch must expose smoke max-attempts control"
        )

    def test_deploy_does_not_run_reset_helper(self, deploy_yml):
        assert "reset_dev_resource_group.py" not in deploy_yml, (
            "deploy.yml should no longer call the clean-reset helper once "
            "manual teardown owns resource deletion"
        )

    def test_deploy_manual_teardown_path_only_prunes_state(self, deploy_yml):
        assert "rebuild_after_manual_teardown" in deploy_yml, (
            "deploy.yml must gate stale-state pruning behind the manual teardown input"
        )
        assert '"Microsoft.KeyVault/vaults"' not in deploy_yml, (
            "deploy.yml should not embed bootstrap preservation rules once teardown is manual"
        )

    def test_deploy_drops_stale_azapi_state_after_manual_teardown(self, deploy_yml):
        assert "Drop stale azapi state after manual teardown" in deploy_yml, (
            "deploy.yml must clear stale azapi state after manual teardown so tofu plan "
            "can recreate deleted resources"
        )
        assert "tofu state rm" in deploy_yml, (
            "deploy.yml manual teardown path must prune stale azapi resources "
            "from state before tofu plan"
        )

    def test_deploy_reconciles_event_grid_subscription(self, deploy_yml):
        assert "reconcile_eventgrid_subscription.py" in deploy_yml, (
            "deploy.yml must reconcile the Event Grid webhook after "
            "readiness so ingestion wiring is restored"
        )

    def test_deploy_sets_keda_queue_trigger_for_activities_app(self, deploy_yml):
        assert "azure-queue" in deploy_yml, (
            "deploy.yml must configure an azure-queue KEDA trigger on the backing "
            "Microsoft.App/containerApps resource so the activities app wakes from "
            "zero replicas when Durable Task work items arrive. "
            "functionAppConfig.scaleAndConcurrency.triggers is Flex-Consumption-only "
            "and silently ignored for azurecontainerapps kind."
        )

    def test_deploy_keda_uses_container_apps_api(self, deploy_yml):
        assert "Microsoft.App/containerApps" in deploy_yml, (
            "KEDA scale rules must be set via the Microsoft.App/containerApps API — "
            "functionAppConfig triggers are Flex-Consumption-only and silently "
            "ignored for azurecontainerapps kind"
        )

    def test_deploy_keda_trigger_uses_keyless_connection(self, deploy_yml):
        assert "accountName" in deploy_yml, (
            "KEDA azure-queue trigger must use accountName metadata (managed-identity / "
            "keyless auth, identity=system) — do not use a storage connection string"
        )

    def test_deploy_keda_queue_name_derived_from_host_json(self, deploy_yml):
        assert "host.json" in deploy_yml, (
            "deploy.yml must derive the Durable Task work-items queue name from "
            "host.json so the KEDA trigger stays in sync when the hub name changes"
        )

    def test_deploy_surfaces_stuck_arm_operation_diagnostics(self, deploy_yml):
        assert "another operation is in progress" in deploy_yml, (
            "deploy.yml must detect stuck ARM write locks so retries do not hide "
            "the blocking operation"
        )
        assert 'az monitor activity-log list --resource-id "$FUNC_ID"' in deploy_yml, (
            "deploy.yml must emit recent write activity for compute app lock diagnosis"
        )
        assert 'az monitor activity-log list --resource-id "$ORCH_ID"' in deploy_yml, (
            "deploy.yml must emit recent write activity for orchestrator lock diagnosis"
        )

    def test_deploy_stuck_arm_lock_detection_fails_fast(self, deploy_yml):
        lock_blocks = re.findall(
            (
                r'if echo "\$PATCH_ERROR" \| grep -qi "another operation is in progress"; '
                r"then(.*?)fi"
            ),
            deploy_yml,
            re.DOTALL,
        )
        assert len(lock_blocks) >= 2, (
            "deploy.yml must have stuck ARM lock detection blocks for both "
            "compute and orchestrator Function Apps"
        )
        for block in lock_blocks:
            assert "exit 1" in block, (
                "deploy.yml stuck ARM lock handling must fail fast so deploy "
                "does not continue with a blocked write path"
            )

    def test_event_grid_reconcile_step_uses_orchestrator_outputs(self, deploy_yml):
        match = re.search(
            r"- name: Reconcile Event Grid subscription(?P<body>.*?)(?:\n\s*- name:|\Z)",
            deploy_yml,
            re.DOTALL,
        )
        assert match, "deploy.yml must include the Event Grid reconcile step"
        body = match.group("body")
        assert "tofu output -raw function_app_orch_name" in body, (
            "Event Grid reconcile step must read the orchestrator function app name"
        )
        assert "tofu output -raw function_app_orch_default_hostname" in body, (
            "Event Grid reconcile step must read the orchestrator hostname"
        )
        assert "tofu output -raw function_app_name" not in body, (
            "Event Grid reconcile step must not read the compute app name"
        )
        assert "tofu output -raw function_app_default_hostname" not in body, (
            "Event Grid reconcile step must not read the compute hostname"
        )

    def test_deploy_validates_infra_gate(self, deploy_yml):
        assert "validate_dev_infra_gate.py" in deploy_yml, (
            "deploy.yml must validate the infra gate after reconciliation "
            "so clean-slate redeploy failures stop the job"
        )

    def test_deploy_runs_async_functional_smoke_gate(self, deploy_yml):
        assert "Run async functional smoke gate" in deploy_yml, (
            "deploy.yml must run an async functional smoke gate after readiness checks"
        )
        assert "/api/internal-smoke" in deploy_yml, (
            "deploy.yml async smoke gate must target the internal deploy smoke endpoint"
        )
        expected_curl_probe = (
            "curl -sS --connect-timeout 5 --max-time 15 "
            '-o /tmp/internal-smoke.json -w "%{http_code}"'
        )
        assert expected_curl_probe in deploy_yml, (
            "deploy.yml async smoke gate must probe the internal smoke endpoint via curl"
        )
        assert '|| echo "000"' in deploy_yml, (
            "deploy.yml async smoke gate must tolerate transient curl failures "
            "and continue bounded retries"
        )

    def test_async_smoke_gate_is_bounded(self, deploy_yml):
        assert "SMOKE_POLL_INTERVAL" in deploy_yml, (
            "deploy.yml async smoke gate must define bounded poll interval"
        )
        assert "SMOKE_MAX_ATTEMPTS" in deploy_yml, (
            "deploy.yml async smoke gate must define bounded max attempts"
        )
        assert 'for attempt in $(seq 1 "$SMOKE_MAX_ATTEMPTS")' in deploy_yml, (
            "deploy.yml async smoke gate must use bounded retry attempts"
        )
        assert 'sleep "$SMOKE_POLL_INTERVAL"' in deploy_yml, (
            "deploy.yml async smoke gate must wait using bounded poll interval"
        )

    def test_infra_gate_step_uses_orchestrator_outputs(self, deploy_yml):
        match = re.search(
            r"- name: Validate infra gate(?P<body>.*?)(?:\n\s*- name:|\Z)",
            deploy_yml,
            re.DOTALL,
        )
        assert match, "deploy.yml must include the infra gate validation step"
        body = match.group("body")
        assert "tofu output -raw function_app_orch_name" in body, (
            "infra gate validation step must read the orchestrator function app name"
        )
        assert "tofu output -raw function_app_orch_default_hostname" in body, (
            "infra gate validation step must read the orchestrator hostname"
        )
        assert "tofu output -raw function_app_name" not in body, (
            "infra gate validation step must not read the compute app name"
        )
        assert "tofu output -raw function_app_default_hostname" not in body, (
            "infra gate validation step must not read the compute hostname"
        )

    def test_deploy_runs_pipeline_smoke_test(self, deploy_yml):
        assert "Run pipeline smoke test" in deploy_yml, (
            "deploy.yml must run a pipeline smoke test after the liveness gate "
            "to verify parse → acquire → fulfil without going through the auth gate"
        )
        assert "pipeline_smoke.py" in deploy_yml, (
            "deploy.yml pipeline smoke step must invoke scripts/pipeline_smoke.py"
        )
        assert "DEPLOY_ENV != 'prd'" in deploy_yml, (
            "deploy.yml pipeline smoke test must be skipped in production "
            "to avoid triggering live imagery acquisition"
        )


class TestStripeKeyVaultBootstrap:
    """Ensure Stripe secret bootstrap tolerates fresh Key Vault RBAC propagation."""

    def test_outputs_expose_cli_managed_function_settings(self):
        outputs_tf = (INFRA / "outputs.tf").read_text()
        assert 'output "function_app_cli_app_settings"' in outputs_tf, (
            "outputs.tf must expose the CLI-managed Function App app settings"
        )
        assert 'output "function_app_cli_maximum_instance_count"' in outputs_tf, (
            "outputs.tf must expose the CLI-managed Function App scale cap"
        )

    def test_deployer_still_has_key_vault_secret_access(self):
        main_tf = MAIN_TF.read_text()
        assert 'role_definition_name = "Key Vault Secrets Officer"' in main_tf, (
            "main.tf must still grant the deployer Key Vault Secrets Officer "
            "for Stripe bootstrap scripts"
        )

    def test_stripe_app_settings_use_stable_key_vault_uris(self):
        main_tf = MAIN_TF.read_text()
        assert "stripe_secret_uris = {" in main_tf, (
            "main.tf must derive Stripe Key Vault references from stable secret names"
        )
        assert "@Microsoft.KeyVault(SecretUri=${local.stripe_secret_uris.api_key})" in main_tf, (
            "Function app settings must reference the stable Stripe API key URI"
        )
        assert 'resource "azurerm_key_vault_secret" "stripe_api_key"' not in main_tf, (
            "Terraform should not recreate Stripe secrets that are already managed in Key Vault"
        )

    def test_tofu_does_not_accept_stripe_secret_values(self):
        variables_tf = VARIABLES_TF.read_text()
        for variable_name in [
            "stripe_api_key",
            "stripe_webhook_secret",
            "stripe_price_id_pro_gbp",
            "stripe_price_id_pro_usd",
            "stripe_price_id_pro_eur",
        ]:
            assert f'variable "{variable_name}"' not in variables_tf, (
                "variables.tf must not accept Stripe secret values once Key Vault "
                "bootstrap owns those secrets"
            )

    def test_appinsights_connection_string_output_exists(self):
        tf = (INFRA / "outputs.tf").read_text()
        assert "appinsights_connection_string" in tf, (
            "outputs.tf must export appinsights_connection_string for the "
            "deploy workflow to inject into the static site"
        )

    def test_appinsights_connection_string_output_is_sensitive(self):
        tf = (INFRA / "outputs.tf").read_text()
        match = re.search(
            r'output\s+"appinsights_connection_string"\s*\{[^}]*\}',
            tf,
            re.DOTALL,
        )
        assert match, "outputs.tf must define appinsights_connection_string output"
        assert "sensitive   = true" in match.group(0) or "sensitive = true" in match.group(0), (
            "appinsights_connection_string output must be marked sensitive=true "
            "to avoid OpenTofu plan failures"
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
        match = re.search(
            r'resource\s+"azapi_resource"\s+"event_grid_subscription"\s*\{(?P<body>.*?)\n\}',
            tf,
            re.DOTALL,
        )
        assert match, "main.tf must define azapi_resource.event_grid_subscription"
        body = match.group("body")
        endpoint_match = re.search(r'endpointUrl\s*=\s*"(?P<url>[^"]+)"', body)
        assert endpoint_match, "event_grid_subscription must define destination endpointUrl"
        endpoint_url = endpoint_match.group("url")
        assert "functionName=blob_trigger" in endpoint_url, (
            "Event Grid webhook endpointUrl must target the blob_trigger function"
        )
        assert "code=${urlencode(local.eventgrid_key)}" in endpoint_url, (
            "Event Grid webhook endpointUrl must include URL-encoded local.eventgrid_key"
        )

    def test_event_grid_webhook_targets_orchestrator_host(self):
        tf = MAIN_TF.read_text()
        assert "azapi_resource.function_app_orch.output.properties.defaultHostName" in tf, (
            "Event Grid webhook endpointUrl must target the orchestrator app hostname"
        )
        assert "azapi_resource.function_app.output.properties.defaultHostName" not in tf, (
            "Event Grid webhook endpointUrl must not target the compute app hostname"
        )

    def test_event_grid_host_key_lookup_targets_orchestrator_app(self):
        tf = MAIN_TF.read_text()
        match = re.search(
            r'resource\s+"azapi_resource_action"\s+"function_host_keys"\s*\{(?P<body>.*?)\n\}',
            tf,
            re.DOTALL,
        )
        assert match, "main.tf must define azapi_resource_action.function_host_keys"
        body = match.group("body")
        assert "resource_id = azapi_resource.function_app_orch.id" in body, (
            "Event Grid host key lookup must target the orchestrator app"
        )
        assert "resource_id = azapi_resource.function_app.id" not in body, (
            "Event Grid host key lookup must not target the compute app"
        )

    def test_event_grid_filter_uses_analysis_prefix_not_extension_suffix(self):
        tf = MAIN_TF.read_text()
        match = re.search(
            r'resource\s+"azapi_resource"\s+"event_grid_subscription"\s*\{(?P<body>.*?)\n\}',
            tf,
            re.DOTALL,
        )
        assert match, "main.tf must define azapi_resource.event_grid_subscription"
        body = match.group("body")
        assert "subjectBeginsWith" in body, (
            "Event Grid subscription must use subjectBeginsWith for analysis blob routing"
        )
        assert "/blobServices/default/containers/kml-input/blobs/analysis/" in body, (
            "Event Grid subject prefix must target analysis blobs in the kml-input container"
        )
        assert "subjectEndsWith" not in body, (
            "Event Grid subscription should not use extension-only suffix filters"
        )


# ---------------------------------------------------------------------------
# 12. Public API ingress docs contract
# ---------------------------------------------------------------------------


class TestPublicApiIngressDocsContract:
    """Public API docs must present orchestrator as the only ingress."""

    @staticmethod
    def _is_in_scope_api_host(host: str) -> bool:
        if host in {"{productionHost}", "{developmentHost}"}:
            return True
        return host.endswith(".azurecontainerapps.io") or host.endswith(".azurewebsites.net")

    @staticmethod
    def _documented_api_hosts(text: str) -> list[str]:
        urls = re.findall(r"https://[A-Za-z0-9{}.-]+", text)
        hosts = [url.replace("https://", "", 1) for url in urls]
        return [
            host for host in hosts if TestPublicApiIngressDocsContract._is_in_scope_api_host(host)
        ]

    @classmethod
    def _assert_uses_orchestrator_ingress_only(cls, text: str, *, source: str) -> None:
        hosts = cls._documented_api_hosts(text)
        assert hosts, f"{source} must document at least one API host"
        assert not any(
            host == "azurestaticapps.net" or host.endswith(".azurestaticapps.net") for host in hosts
        ), f"{source} must not use Static Web App hostnames as API ingress"
        assert not any(re.fullmatch(r"func-kmlsat-dev\.[A-Za-z0-9.-]+", host) for host in hosts), (
            f"{source} must not document the compute ingress hostname"
        )
        assert any(host == "{productionHost}" or "-orch" in host for host in hosts), (
            f"{source} must use orchestrator ingress (or production host variable)"
        )

    def test_api_interface_reference_uses_orchestrator_base_url(self):
        text = API_INTERFACE_REFERENCE.read_text()
        self._assert_uses_orchestrator_ingress_only(text, source="API interface reference")

    def test_openapi_production_server_uses_orchestrator_ingress(self):
        text = OPENAPI_YAML.read_text()
        self._assert_uses_orchestrator_ingress_only(text, source="OpenAPI servers")
        assert "azurestaticapps.net/api" not in text, (
            "OpenAPI production server must not point to the static web app hostname"
        )

    def test_event_grid_webhook_targets_orchestrator_hostname(self):
        tf = MAIN_TF.read_text()
        assert "function_app_orch.output.properties.defaultHostName" in tf, (
            "Event Grid subscription must target function_app_orch (orchestrator) hostname, "
            "not function_app (compute) hostname. "
            "Orchestrator is the canonical ingestion pipeline entry point."
        )
        # Defensive check: ensure we're NOT pointing to the compute app
        assert (
            "azapi_resource.function_app.output.properties.defaultHostName}/runtime/webhooks/eventgrid"
            not in tf
        ), (
            "Event Grid webhook must NOT target the compute function_app. "
            "blob_trigger is orchestrator-only and Event Grid must deliver to "
            "the orchestrator hostname."
        )


# ---------------------------------------------------------------------------
# 11. Trivy signal quality and exception discipline
# ---------------------------------------------------------------------------


class TestSemgrepConsistency:
    """Semgrep must be reproducible: pinned, make-driven, no registry drift."""

    def test_semgrep_runs_via_make_sast(self):
        yml = SECURITY_YML.read_text()
        assert "make sast" in yml, (
            "security.yml Semgrep job must delegate to 'make sast' so the exact "
            "config runs identically locally and in CI"
        )
        assert "semgrep scan" not in yml, (
            "security.yml must not invoke 'semgrep scan' inline — use 'make sast'"
        )

    def test_semgrep_does_not_use_config_auto(self):
        makefile = MAKEFILE.read_text()
        yml = SECURITY_YML.read_text()
        assert "--config auto" not in makefile and "--config auto" not in yml, (
            "Semgrep must not use '--config auto' — it selects rules server-side "
            "and drifts, breaking unrelated PRs. Use pinned rule packs."
        )

    def test_sast_target_is_pinned(self):
        makefile = MAKEFILE.read_text()
        assert "sast:" in makefile, "Makefile must define a canonical 'sast' target"
        assert "SEMGREP_VERSION ?=" in makefile, (
            "Makefile must pin the Semgrep version so local and CI match"
        )
        for pack in ("p/python", "p/owasp-top-ten", "p/security-audit"):
            assert pack in makefile, f"sast target must include pinned pack {pack}"

    def test_dependabot_has_cooldown(self):
        cfg = DEPENDABOT_YML.read_text()
        # One cooldown block per ecosystem (pip, github-actions, docker, terraform)
        assert cfg.count("cooldown:") == cfg.count("- package-ecosystem:"), (
            "every dependabot ecosystem must declare a cooldown to avoid adopting "
            "brand-new (possibly compromised) releases immediately"
        )


# ---------------------------------------------------------------------------


class TestTrivySignalQuality:
    """Ensure Trivy scans stay actionable and exceptions remain explicit."""

    def test_security_trivy_fs_ignores_unfixed(self):
        makefile = MAKEFILE.read_text()
        assert (
            "scan-fs:" in makefile
            and '"$$T" fs . $(_TRIVY_IGN) --scanners vuln --severity CRITICAL,HIGH --ignore-unfixed'
            in makefile
        ), "Makefile scan-fs target should ignore unfixed CVEs to reduce non-actionable alert noise"

    def test_deploy_trivy_image_ignores_unfixed(self):
        makefile = MAKEFILE.read_text()
        scan_image_cmd = (
            '"$$T" image $(IMAGE) $(_TRIVY_IGN) $(_TRIVY_SCAN) '
            "--severity CRITICAL,HIGH --ignore-unfixed"
        )
        assert "scan-image:" in makefile and scan_image_cmd in makefile, (
            "Makefile scan-image target should ignore unfixed CVEs "
            "to focus on actionable vulnerabilities"
        )

    def test_trivy_fs_make_uses_trivyignore(self):
        makefile = MAKEFILE.read_text()
        assert "TRIVY_IGNOREFILE ?= .trivyignore" in makefile, (
            "Makefile must default TRIVY_IGNOREFILE to .trivyignore"
        )
        assert '"$$T" fs . $(_TRIVY_IGN)' in makefile, (
            "scan-fs must apply the configured Trivy ignorefile"
        )

    def test_trivy_scans_delegated_to_make(self):
        action = TRIVY_SCAN_ACTION.read_text()
        assert 'make "scan-${SCAN}"' in action, (
            "the trivy-scan composite action must delegate to the canonical "
            "make scan-* targets (single run path)"
        )
        # Inputs must reach the run: script via env (not ${{ }} interpolation)
        # to avoid shell injection — Semgrep run-shell-injection.
        assert "SCAN: ${{ inputs.scan }}" in action, (
            "composite action must pass inputs to the run step via env vars"
        )
        assert 'scan-${{ inputs.scan }}"' not in action, (
            "composite action run: script must not interpolate ${{ inputs }} "
            "directly — pass via env and reference $VAR"
        )
        yml = SECURITY_YML.read_text()
        assert "./.github/actions/trivy-scan" in yml, (
            "security.yml must run Trivy through the shared composite action"
        )
        assert "trivy-action" not in yml, (
            "security.yml should avoid bespoke trivy-action blocks in favor of the "
            "shared composite action"
        )

    def test_base_image_trivy_scan_uses_make(self):
        yml = BASE_IMAGE_YML.read_text()
        assert "./.github/actions/trivy-scan" in yml, (
            "base-image.yml must run Trivy image scanning through the shared "
            "composite action (which delegates to make scan-image)"
        )

    def test_trivy_uses_single_setup_and_run_path(self):
        """The whole point: one setup action, one run path — no duplication.

        setup-trivy and the ``make scan-*`` invocation must live only in the
        composite action, never re-declared inline in a workflow. Each workflow
        that scans references the action by path.
        """
        action = TRIVY_SCAN_ACTION.read_text()
        assert "aquasecurity/setup-trivy@" in action, (
            "the composite action must be the single place Trivy is installed"
        )

        workflow_files = [SECURITY_YML, BASE_IMAGE_YML, DEPLOY_YML]
        for wf in workflow_files:
            text = wf.read_text()
            assert "aquasecurity/setup-trivy@" not in text, (
                f"{wf.name} must not install Trivy inline — use the composite action"
            )
            assert "make scan-" not in text, (
                f"{wf.name} must not call make scan-* inline — use the composite action"
            )
            assert "./.github/actions/trivy-scan" in text, (
                f"{wf.name} must invoke the shared trivy-scan composite action"
            )

    def test_trivy_version_pinned_and_consistent(self):
        """Trivy binary version is pinned (reproducible + supply-chain safe) and
        the Makefile pin matches the composite action default, so local == CI."""
        makefile = MAKEFILE.read_text()
        action = TRIVY_SCAN_ACTION.read_text()
        mk = re.search(r"TRIVY_VERSION \?= ([0-9]+\.[0-9]+\.[0-9]+)", makefile)
        assert mk, "Makefile must pin TRIVY_VERSION to an explicit version"
        act = re.search(r'default:\s*"v([0-9]+\.[0-9]+\.[0-9]+)"', action)
        assert act, "composite action must pin trivy-version to an explicit version"
        assert mk.group(1) == act.group(1), (
            "Makefile TRIVY_VERSION must match the composite action trivy-version "
            f"default ({mk.group(1)} != {act.group(1)}) so local and CI use one version"
        )

    def test_trivy_fs_scans_vulnerabilities_only(self):
        """scan-fs scans vulns only; secret detection is owned by the dedicated
        detect-secrets job (avoids duplicate/false-positive secret findings)."""
        makefile = MAKEFILE.read_text()
        scan_fs = re.search(r"^scan-fs:.*?(?=^\S)", makefile, re.MULTILINE | re.DOTALL)
        assert scan_fs and "--scanners vuln" in scan_fs.group(0), (
            "Makefile scan-fs must pass --scanners vuln (detect-secrets owns secrets)"
        )

    def test_trivy_ignore_file_exists(self):
        assert TRIVY_IGNORE.exists(), (
            ".trivyignore must exist for temporary, documented risk exceptions"
        )

    def test_trivy_ignore_tracks_low_cost_network_acl_exceptions(self):
        ignore = TRIVY_IGNORE.read_text()
        assert "AZU-0012" in ignore and "AZU-0013" in ignore, (
            ".trivyignore must explicitly track current low-cost network ACL exceptions"
        )

    def test_trivy_ignore_has_no_container_cve_suppressions(self):
        ignore = TRIVY_IGNORE.read_text()
        non_comment_entries = [
            line.strip()
            for line in ignore.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        cve_entries = [line for line in non_comment_entries if line.startswith("CVE-")]
        assert cve_entries == [], (
            ".trivyignore must not contain container CVE suppressions; "
            "HIGH/CRITICAL container findings must be fixed at source"
        )

    def test_security_workflow_checks_trivyignore_expiry(self):
        yml = SECURITY_YML.read_text()
        assert "Trivyignore Expiry Check" in yml, (
            "security.yml must run a dedicated .trivyignore expiry check job"
        )
        assert "Validate .trivyignore expiries" in yml, (
            "security.yml must validate exp:YYYY-MM-DD metadata for .trivyignore entries"
        )

    def test_trivyignore_expiry_policy_is_enforced(self):
        yml = SECURITY_YML.read_text()
        assert "missing exp:YYYY-MM-DD metadata" in yml, (
            "security.yml expiry check must fail when .trivyignore entries lack exp metadata"
        )
        assert "expires soon" in yml and "timedelta(days=14)" in yml, (
            "security.yml expiry check must warn for entries expiring within 14 days"
        )


# ---------------------------------------------------------------------------
# 13. Container runtime prerequisites
# ---------------------------------------------------------------------------


class TestContainerRuntimePrereqs:
    """Validate that Dockerfile.base includes all .NET host requirements."""

    BASE_DOCKERFILE = ROOT / "Dockerfile.base"

    def test_libicu_in_dockerfile_base(self):
        """libicu must be installed — .NET host crashes without ICU."""
        content = self.BASE_DOCKERFILE.read_text()
        assert re.search(r"libicu\d*", content), (
            "Dockerfile.base must install libicu (e.g. libicu72) — "
            ".NET Functions host crashes at startup without ICU globalization support"
        )

    def test_smoke_test_checks_icu(self):
        """Container smoke test must verify ICU is present."""
        smoke = (ROOT / "scripts" / "container_smoke_test.py").read_text()
        assert "libicu" in smoke.lower(), "container_smoke_test.py must check for libicu presence"

    def test_no_host_dll_deletion_in_dockerfile(self):
        """Host DLLs must NOT be deleted — host lazily loads them at startup.

        Deleting CodeAnalysis, NuGet.Packaging, NuGet.Versioning etc. has
        caused three consecutive deploy outages.  Only PDB/XML are safe to strip.
        """
        content = self.BASE_DOCKERFILE.read_text()
        # Extract the host optimisation RUN block (between "cd /azure-functions-host"
        # and the next blank line / Stage marker).  Bundle-level rm is fine.
        host_match = re.search(
            r"(cd /azure-functions-host.*?)(?:\n\n|# ── Bundle|# ── Stage)",
            content,
            flags=re.DOTALL,
        )
        if host_match:
            host_section = host_match.group(1)
            assert not re.search(r"\brm\b[^\n]*\.dll", host_section, flags=re.IGNORECASE), (
                "Dockerfile.base host section must not rm any .dll files"
            )
            assert not re.search(
                r"find\b[^\n]*\.dll[^\n]*-delete", host_section, flags=re.IGNORECASE
            ), "Dockerfile.base host section must not find -delete any .dll files"

    def test_smoke_test_checks_host_dlls(self):
        """Container smoke test must verify critical host DLLs are present."""
        smoke = (ROOT / "scripts" / "container_smoke_test.py").read_text()
        for dll in ["NuGet.Versioning.dll", "NuGet.Packaging.dll", "Microsoft.CodeAnalysis.dll"]:
            assert dll in smoke, f"container_smoke_test.py must check for {dll} presence"


# ---------------------------------------------------------------------------
# 14. Submission endpoint CORS parity
# ---------------------------------------------------------------------------


class TestSubmissionCORSParity:
    """Both demo and authenticated submission must include CORS headers.

    Bug: _submit_analysis_request returned responses without CORS headers,
    causing browsers to block the response on cross-origin requests.  The
    frontend then showed a generic 'Could not queue analysis request' error
    instead of the real error message.
    """

    SUBMISSION_PY = ROOT / "blueprints" / "pipeline" / "submission.py"

    def test_analysis_submit_returns_cors_headers(self):
        """The authenticated 202 response must include headers=cors_headers(req)."""
        content = self.SUBMISSION_PY.read_text()
        # Find the _submit_analysis_request function
        fn_match = re.search(
            r"async def _submit_analysis_request\b.*?(?=\nasync def |\nclass |\Z)",
            content,
            flags=re.DOTALL,
        )
        assert fn_match, "_submit_analysis_request not found in submission.py"
        fn_body = fn_match.group(0)

        # Every HttpResponse in this function should have cors_headers
        responses = re.findall(r"func\.HttpResponse\(.*?\n\s*\)", fn_body, flags=re.DOTALL)
        for resp_call in responses:
            assert "cors_headers" in resp_call or "_error_response" in resp_call, (
                f"HttpResponse in _submit_analysis_request missing cors_headers: {resp_call[:80]}"
            )

    def test_error_response_includes_cors_headers(self):
        """error_response should accept a request and include CORS headers."""
        helpers = (ROOT / "blueprints" / "_helpers.py").read_text()
        fn_match = re.search(
            r"def error_response\b.*?(?=\ndef |\nclass |\Z)",
            helpers,
            flags=re.DOTALL,
        )
        assert fn_match, "error_response not found in _helpers.py"
        fn_body = fn_match.group(0)
        assert "Access-Control-Allow-Origin" in fn_body or "cors" in fn_body.lower(), (
            "error_response must include CORS headers so error responses "
            "are not blocked by CORS policy"
        )


# ---------------------------------------------------------------------------
# 15. Frontend progress animation reset on submission error
# ---------------------------------------------------------------------------


class TestFrontendProgressReset:
    """The pipeline progress animation must be hidden when submission fails.

    Bug: queueAnalysis() showed the progress spinner before the API call
    but did not reset it in the error branch (only in the catch block),
    leaving a spinning animation on a failed submission.
    """

    APP_RUN_LIFECYCLE = WEBSITE / "js" / "app-run-lifecycle.js"

    def test_queue_error_branch_resets_progress(self):
        """Error branches in queueAnalysis must call resetAnalysisProgress()."""
        content = self.APP_RUN_LIFECYCLE.read_text()
        # Find the queueAnalysis function
        fn_start = content.find("async function queueAnalysis()")
        assert fn_start != -1, "queueAnalysis function not found in app-run-lifecycle.js"

        # Extract until next top-level function (heuristic: next 'async function' or '  function')
        fn_end = content.find("\n  async function ", fn_start + 1)
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]

        assert "resetAnalysisProgress" in fn_body, (
            "queueAnalysis must call resetAnalysisProgress() in error paths "
            "to hide the pipeline spinner when submission fails"
        )


class TestFrontendQueueFallback:
    """Queue flow should fall back to direct API submit when SAS upload fails."""

    APP_RUN_LIFECYCLE = WEBSITE / "js" / "app-run-lifecycle.js"

    def test_queue_flow_has_direct_submit_fallback(self):
        content = self.APP_RUN_LIFECYCLE.read_text()
        assert "function queueAnalysisViaSubmitApi" in content, (
            "app-run-lifecycle.js must define a direct submit fallback helper"
        )
        assert "'/api/analysis/submit'" in content, (
            "queue fallback must call /api/analysis/submit when direct blob upload fails"
        )

    def test_queue_fallback_preserves_401_auth_ux(self):
        content = self.APP_RUN_LIFECYCLE.read_text()
        assert "submitFetchErr.status === 401" in content, (
            "direct-submit fallback must preserve session-expired auth handling for 401 errors"
        )


class TestSignedOutStatusBadge:
    """Navbar service status badge should be hidden when no account is signed in."""

    APP_MSAL = WEBSITE / "js" / "app-msal.js"

    def test_signed_out_hides_status_badge(self):
        content = self.APP_MSAL.read_text()
        fn_start = content.find("function renderSignedOutUI(elements)")
        assert fn_start != -1, "renderSignedOutUI not found in app-msal.js"
        fn_end = content.find("\n  function ", fn_start + 1)
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]
        assert "elements.statusBadge" in fn_body and "style.display = 'none'" in fn_body, (
            "renderSignedOutUI must hide the navbar status badge"
        )


# ---------------------------------------------------------------------------
# 13. Infracost cost-gate workflow and usage file
# ---------------------------------------------------------------------------


class TestCIFeedbackHygiene:
    """PR CI should give fast feedback: cache deps + cancel superseded runs."""

    def test_pr_workflows_cancel_superseded_runs(self):
        for wf in (CI_YML, SECURITY_YML, CODEQL_YML, PREVIEW_SITE_YML):
            text = wf.read_text()
            assert "concurrency:" in text and "cancel-in-progress:" in text, (
                f"{wf.name} must define a concurrency group so superseded PR runs "
                "are cancelled (fast feedback, less wasted compute)"
            )

    def test_deploy_never_cancels_in_progress(self):
        # Deploys must run to completion — never cancel a deploy mid-flight.
        assert "cancel-in-progress: false" in DEPLOY_YML.read_text(), (
            "deploy.yml must keep cancel-in-progress: false"
        )

    def test_uv_setup_enables_cache(self):
        # Any workflow that still provisions uv per-job must enable caching to
        # avoid re-resolving the environment on every run. The CI gate jobs no
        # longer use setup-uv at all — they run inside the prebuilt dev image
        # (see test_ci_gate_jobs_run_in_dev_image) — so this only bites the
        # workflows that genuinely still call setup-uv.
        for wf in (CI_YML, SECURITY_YML):
            text = wf.read_text()
            if "astral-sh/setup-uv" not in text:
                continue
            assert "enable-cache: true" in text, (
                f"{wf.name} setup-uv steps must enable caching to avoid re-resolving "
                "the environment on every job"
            )

    def test_ci_gate_jobs_run_in_dev_image(self):
        """The lint/test/integration gates run *inside* the published dev image
        by digest (deps baked in) rather than provisioning uv per job, so
        `local == CI` is the same image. Only image build/publish stays on the
        bare runner. See #1086 / ADR 0005."""
        workflow = yaml.safe_load(CI_YML.read_text())
        jobs = workflow["jobs"]
        assert "resolve-image" in jobs, (
            "ci.yml must define a resolve-image job that pins the dev image digest"
        )
        # lint/test run directly as container jobs (job container == dev image).
        for job_id in ("lint", "test"):
            job = jobs[job_id]
            needs = job.get("needs")
            needs = [needs] if isinstance(needs, str) else (needs or [])
            assert "resolve-image" in needs, (
                f"{job_id} must depend on resolve-image for the pinned digest"
            )
            container = job.get("container") or {}
            assert "needs.resolve-image.outputs.image" in str(container.get("image", "")), (
                f"{job_id} must run inside the resolved dev image (by digest)"
            )
            steps_text = yaml.dump(job.get("steps"))
            assert "astral-sh/setup-uv" not in steps_text, (
                f"{job_id} must not provision uv — deps are baked into the dev image"
            )
        # integration drives docker compose on the bare runner because Azurite
        # needs --skipApiVersionCheck (impossible via a GitHub `services:`
        # container), but it still executes the suite INSIDE the resolved dev
        # image via the ci-gate compose service. See #1086.
        integ = jobs["integration"]
        needs = integ.get("needs")
        needs = [needs] if isinstance(needs, str) else (needs or [])
        assert "resolve-image" in needs, (
            "integration must depend on resolve-image for the pinned digest"
        )
        integ_text = yaml.dump(integ)
        assert "needs.resolve-image.outputs.image" in integ_text, (
            "integration must run the gate inside the resolved dev image "
            "(passed to the ci-gate service via CI_GATE_IMAGE)"
        )
        assert "docker compose" in integ_text and "ci-gate" in integ_text, (
            "integration must drive the azurite + ci-gate compose services "
            "(Azurite needs --skipApiVersionCheck, unavailable to a services: container)"
        )
        assert "astral-sh/setup-uv" not in integ_text, (
            "integration must not provision uv — deps are baked into the dev image"
        )

    def test_compose_azurite_skips_api_version_check(self):
        """The azurite service must keep --skipApiVersionCheck (and --loose):
        the installed azure-storage SDK negotiates an API version newer than
        Azurite ships, so without the skip every request is rejected and the
        integration suite (local and CI) fails to reach storage. See #1086."""
        compose = yaml.safe_load(COMPOSE_YML.read_text())
        azurite = compose["services"]["azurite"]
        command = azurite.get("command", "")
        assert "--skipApiVersionCheck" in command, (
            "docker-compose azurite must pass --skipApiVersionCheck so the SDK's "
            "API version is accepted (else all storage calls 400/403)"
        )

    def test_pr_workflows_run_on_ready_for_review(self):
        """Promoting a draft must trigger CI — so pull_request needs the
        ready_for_review type (otherwise a promoted draft runs nothing). #1003."""
        for wf in (CI_YML, SECURITY_YML, CODEQL_YML):
            workflow = yaml.safe_load(wf.read_text())
            # PyYAML parses the bare `on:` key as the boolean True.
            pr = (workflow.get(True) or {}).get("pull_request") or {}
            assert "ready_for_review" in (pr.get("types") or []), (
                f"{wf.name} pull_request trigger must include 'ready_for_review' so "
                "promoting a draft (manual or auto) actually runs CI"
            )

    def test_actionlint_gates_workflows_in_ci(self):
        """Workflow YAML is linted through a single route — `make lint-actions` —
        used by both CI and the local pre-commit hook, so the actionlint version
        and shellcheck rule suppressions (both in the Makefile) cannot drift.
        #995, #1080."""
        assert ACTIONLINT_YML.exists(), "actionlint.yml CI workflow must exist"
        wf = ACTIONLINT_YML.read_text()
        # CI must invoke the canonical make target, not an inline binary run.
        assert "make lint-actions" in wf, (
            "actionlint.yml must run `make lint-actions` (single route shared with local)"
        )
        assert "SHELLCHECK_OPTS" not in wf, (
            "shellcheck rules must live in .shellcheckrc, not inline in the workflow"
        )

        # The pinned version, target, and shellcheck rule suppressions all live
        # in the Makefile as the single source of truth (matching the
        # SEMGREP_VERSION / TRIVY_VERSION pattern). actionlint feeds scripts to
        # shellcheck via stdin, so a repo-root .shellcheckrc is not honoured —
        # the suppressions must ride on SHELLCHECK_OPTS from the make target.
        makefile = MAKEFILE.read_text()
        assert "lint-actions:" in makefile, (
            "Makefile must define the canonical 'lint-actions' target"
        )
        assert re.search(r"ACTIONLINT_VERSION \?= [0-9.]+", makefile), (
            "Makefile must pin ACTIONLINT_VERSION as the single source of truth"
        )
        assert "SC2129" in makefile and "SC2016" in makefile, (
            "Makefile lint-actions must carry the shellcheck suppressions "
            "(single source shared by CI and local pre-commit)"
        )

        # Local pre-commit must route through the same make target, not pin its
        # own separate actionlint version.
        pc = (ROOT / ".pre-commit-config.yaml").read_text()
        assert "make lint-actions" in pc, (
            "pre-commit actionlint hook must run `make lint-actions` so local == CI"
        )
        assert "rhysd/actionlint" not in pc, (
            "pre-commit must not pin a separate actionlint version; use make lint-actions"
        )


class TestInfracostCostGate:
    """Verify Infracost CI gate is properly configured."""

    def test_infracost_workflow_exists(self):
        assert INFRACOST_YML.exists(), (
            "Infracost workflow missing at .github/workflows/infracost.yml"
        )

    def test_infracost_usage_file_exists(self):
        assert INFRACOST_USAGE.exists(), (
            "Infracost usage file missing at infra/tofu/infracost-usage.yml"
        )

    def test_infracost_workflow_triggers_on_infra_changes(self):
        content = INFRACOST_YML.read_text()
        assert "infra/tofu/**" in content, (
            "Infracost workflow must trigger on infra/tofu/** changes"
        )

    def test_infracost_workflow_has_budget_check(self):
        content = INFRACOST_YML.read_text()
        assert "budget" in content.lower(), (
            "Infracost workflow must include a budget threshold check"
        )

    def test_infracost_usage_file_has_version(self):
        content = INFRACOST_USAGE.read_text()
        assert "version:" in content, "Infracost usage file must declare a version"

    def test_infracost_usage_file_covers_key_resources(self):
        content = INFRACOST_USAGE.read_text()
        expected = [
            "azurerm_log_analytics_workspace.main",
            "azurerm_storage_account.main",
            "azurerm_key_vault.main",
        ]
        for resource in expected:
            assert resource in content, (
                f"Infracost usage file must have usage parameters for {resource}"
            )

    def test_collection_script_exists(self):
        script = ROOT / "scripts" / "collect_infracost_usage.py"
        assert script.exists(), (
            "Usage metrics collection script missing at scripts/collect_infracost_usage.py"
        )

    def test_infracost_optional_deps_defined(self):
        pyproject = ROOT / "pyproject.toml"
        content = pyproject.read_text()
        assert "[project.optional-dependencies]" in content
        assert "infracost" in content, (
            "pyproject.toml must define an 'infracost' optional dep group"
        )


# ---------------------------------------------------------------------------
# 14. PR linked-issue enforcement gate (#945)
# ---------------------------------------------------------------------------


class TestLinkedIssuePullRequestGate:
    """Ensure PRs are blocked unless they declare a closing issue reference."""

    def test_linked_issue_workflow_exists(self):
        assert REQUIRE_LINKED_ISSUE_YML.exists(), (
            "Linked-issue workflow missing at .github/workflows/require-linked-issue.yml"
        )

    def test_linked_issue_check_context_name_is_stable(self):
        content = REQUIRE_LINKED_ISSUE_YML.read_text()
        assert "name: check-issue-link" in content, (
            "Linked-issue workflow job must be named 'check-issue-link' "
            "so it can be required by branch protection"
        )

    def test_linked_issue_workflow_validates_closing_keywords(self):
        content = REQUIRE_LINKED_ISSUE_YML.read_text()
        assert "closes/fixes/resolves" in content.lower()
        pattern_match = re.search(r"pattern=(['\"])(.+?)\1", content)
        assert pattern_match, "Linked-issue workflow must define a regex pattern for PR body checks"
        pattern = re.compile(pattern_match.group(2), re.IGNORECASE)
        assert pattern.search("closes #945")
        assert pattern.search("Fixes Hardcoreprawn/azure-workflow-for-kml-satellite#945")
        assert pattern.search("resolves #945")
        assert not pattern.search("related to #945"), (
            "Linked-issue workflow must enforce closes/fixes/resolves #NNN in PR body"
        )

    def test_pull_request_template_prompts_issue_link(self):
        content = PULL_REQUEST_TEMPLATE.read_text().lower()
        assert "closes #" in content or "fixes #" in content or "resolves #" in content, (
            "PR template must prompt authors to include closes/fixes/resolves #NNN"
        )

    def test_dependabot_exempt_by_authenticated_identity_only(self):
        """Dependabot is waived from the linked-issue gate, but ONLY via the
        unspoofable authenticated author identity — never branch/title/commit."""
        content = REQUIRE_LINKED_ISSUE_YML.read_text()
        # Exemption keys off the GitHub-authenticated PR author login.
        assert "PR_AUTHOR: ${{ github.event.pull_request.user.login }}" in content, (
            "exemption must read the authenticated pull_request.user.login"
        )
        assert '"$PR_AUTHOR" = "dependabot[bot]"' in content, (
            "exemption must match the dependabot[bot] identity exactly"
        )
        # Must NOT key off spoofable signals.
        assert "head_ref" not in content and "head.ref" not in content, (
            "exemption must not trust the (forgeable) branch name"
        )
        assert "pull_request.title" not in content, (
            "exemption must not trust the (forgeable) PR title"
        )
        # Broad bot allowlisting would let any installed App bypass the gate.
        assert "user.type" not in content, (
            "do not exempt all bots (user.type == 'Bot'); allowlist dependabot only"
        )


# ---------------------------------------------------------------------------
# 15. KML polygon-with-hole parsing (#580)
# ---------------------------------------------------------------------------


class TestParseKmlGeometryHoleHandling:
    """Regression: parseKmlGeometry must not count innerBoundaryIs as extra polygons.

    A Placemark with a polygon hole (outerBoundaryIs + innerBoundaryIs) was
    producing 2 polygon entries instead of 1, causing "56 features across 57
    AOIs" in the preflight panel. The fix extracts coordinates only from
    outerBoundaryIs elements when present.
    """

    APP_SHELL = WEBSITE / "js" / "canopex-geo.js"

    def test_uses_outer_boundary_extraction(self):
        """parseKmlGeometry must look for outerBoundaryIs before extracting coordinates."""
        content = self.APP_SHELL.read_text()
        fn_start = content.find("function parseKmlGeometry(")
        assert fn_start != -1, "parseKmlGeometry not found in canopex-geo.js"

        fn_end = content.find("\n  function ", fn_start + 1)
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]

        assert "outerBoundaryIs" in fn_body, (
            "parseKmlGeometry must extract coordinates from outerBoundaryIs "
            "to avoid counting innerBoundaryIs (holes) as separate polygons (#580)"
        )

    def test_does_not_blindly_iterate_all_coordinates(self):
        """The primary Placemark loop must not use getElementsByTagName('coordinates') directly."""
        content = self.APP_SHELL.read_text()
        fn_start = content.find("function parseKmlGeometry(")
        fn_end = content.find("\n  function ", fn_start + 1)
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]

        # The first coordinates extraction inside the Placemark loop should
        # go through outerBoundaryIs, not directly on the Placemark.
        # The fallback (no outerBoundaryIs) is fine, but the primary path
        # must not blindly grab all <coordinates> from a Placemark.
        placemark_loop_start = fn_body.find("for (var p = 0;")
        assert placemark_loop_start != -1, "Placemark loop not found"
        loop_body = fn_body[placemark_loop_start:]

        # outerBoundaryIs check must appear before any raw getElementsByTagName('coordinates')
        outer_idx = loop_body.find("outerBoundaryIs")
        raw_coord_idx = loop_body.find("getElementsByTagName('coordinates')")
        assert outer_idx < raw_coord_idx, (
            "parseKmlGeometry must check outerBoundaryIs before falling back "
            "to raw coordinates extraction (#580)"
        )


# ---------------------------------------------------------------------------
# 16. EUDR mode toggle wiring (#600)
# ---------------------------------------------------------------------------


class TestEudrModeToggle:
    """EUDR mode checkbox must exist in HTML, be wired in JS, and be tier-gated."""

    APP_SHELL = WEBSITE / "js" / "app-shell.js"
    APP_BILLING = WEBSITE / "js" / "app-billing.js"
    APP_EVIDENCE_DISPLAY = WEBSITE / "js" / "app-evidence-display.js"
    APP_RUN_LIFECYCLE = WEBSITE / "js" / "app-run-lifecycle.js"
    APP_HTML = WEBSITE / "app" / "index.html"

    def test_eudr_checkbox_exists_in_html(self):
        content = self.APP_HTML.read_text()
        assert 'id="app-eudr-mode"' in content, (
            "EUDR mode checkbox with id='app-eudr-mode' must exist in app/index.html"
        )

    def test_eudr_toggle_hidden_by_default(self):
        content = self.APP_HTML.read_text()
        assert 'id="app-eudr-toggle" hidden' in content, (
            "EUDR toggle container must be hidden by default (shown only for paid tiers)"
        )

    def test_js_reads_eudr_checkbox_in_queue(self):
        content = self.APP_RUN_LIFECYCLE.read_text()
        fn_start = content.find("async function queueAnalysis()")
        assert fn_start != -1
        fn_end = content.find("\n  async function ", fn_start + 1)
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]
        assert "app-eudr-mode" in fn_body, "queueAnalysis must read the EUDR checkbox value (#600)"
        assert "eudr_mode" in fn_body, "queueAnalysis must set eudr_mode on the token body (#600)"

    def test_js_gates_toggle_visibility_by_tier(self):
        content = self.APP_BILLING.read_text()
        assert "app-eudr-toggle" in content, "applyBillingStatus must manage EUDR toggle visibility"
        # Must check for paid tiers
        assert "paidTiers" in content or "starter" in content, (
            "EUDR toggle visibility must be gated on paid tier list"
        )

    def test_eudr_request_uses_selected_aoi_context(self):
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        fn_start = content.find("async function requestEudrAssessment()")
        assert fn_start != -1, "requestEudrAssessment function not found in app-evidence-display.js"
        fn_end = content.find(
            "\n  /* ------------------------------------------------------------------ */",
            fn_start,
        )
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]
        assert "activeEvidenceContext" in content, (
            "app-evidence-display.js must define a helper that resolves the active parcel context"
        )
        assert "activeEvidenceContext()" in fn_body or (
            "evidenceSelectedAoi" in fn_body and "per_aoi_enrichment" in fn_body
        ), "requestEudrAssessment must pivot to the selected parcel when a per-AOI chip is active"

    def test_eudr_request_uses_real_ndvi_dates(self):
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        fn_start = content.find("async function requestEudrAssessment()")
        assert fn_start != -1, "requestEudrAssessment function not found in app-evidence-display.js"
        fn_end = content.find(
            "\n  /* ------------------------------------------------------------------ */",
            fn_start,
        )
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]
        assert "buildEvidenceNdviTimeseries" in content, (
            "app-evidence-display.js must define a helper that builds"
            " dated NDVI timeseries for evidence requests"
        )
        assert (
            "buildEvidenceNdviTimeseries(source)" in fn_body
            or "f.datetime" in fn_body
            or "fp.start" in fn_body
        ), "requestEudrAssessment must send a real NDVI observation date, not only a display label"


class TestEvidenceMapQualityGate:
    """Ensure the evidence map respects frame-plan display quality metadata."""

    APP_EVIDENCE_DISPLAY = WEBSITE / "js" / "app-evidence-display.js"

    def test_evidence_map_reads_frame_quality_metadata(self):
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        assert "rgb_display_suitable" in content, (
            "app-evidence-display.js must read frame_plan.rgb_display_suitable "
            "so coarse RGB frames can be demoted"
        )
        assert "preferred_layer" in content, (
            "app-evidence-display.js must read frame_plan.preferred_layer "
            "to choose RGB vs NDVI intelligently"
        )

    def test_evidence_map_chooses_default_layer_from_frame_plan(self):
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        assert "pickEvidenceDefaultLayer" in content, (
            "app-evidence-display.js must define a helper that chooses the default evidence layer "
            "from frame metadata"
        )

    def test_evidence_map_chooses_initial_frame_from_best_display_candidate(self):
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        assert "pickInitialEvidenceFrameIndex" in content, (
            "app-evidence-display.js must define a helper that picks the initial evidence frame "
            "from the best available display candidate, not always frame 0"
        )
        assert "showEvidenceFrame(evidenceFrameIndex)" in content, (
            "buildEvidenceFrames must open the chosen initial evidence frame rather "
            "than hard-coding showEvidenceFrame(0)"
        )

    def test_layer_button_labels_update_per_frame(self):
        """#646 — layer picker shows per-frame collection + resolution as button labels."""
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        assert "updateLayerButtonLabels" in content, (
            "app-evidence-display.js must define updateLayerButtonLabels(frame) so each frame's "
            "collection and resolution are surfaced in the layer picker buttons"
        )

    def test_layer_mode_falls_back_to_rgb_when_ndvi_unavailable(self):
        """#646 — navigating to a frame without NDVI must not leave the viewer broken."""
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        assert "evidenceLayerMode === 'ndvi' && !activeFrame.ndvi" in content, (
            "showEvidenceFrame must fall back from ndvi to rgb when the active frame "
            "has no ndvi layer, so the viewer never shows a blank tile"
        )

    def test_layer_picker_stores_collection_label_per_frame(self):
        """#646 — buildEvidenceFrames must record collectionLabel per entry."""
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        assert "collectionLabel" in content, (
            "buildEvidenceFrames must store a collectionLabel per map-layer entry "
            "so updateLayerButtonLabels has per-frame context without re-reading the DOM"
        )

    def test_layer_mode_buttons_synced_on_init(self):
        """#690 review — buildEvidenceFrames must sync button active state after setting mode."""
        content = self.APP_EVIDENCE_DISPLAY.read_text()
        assert "syncLayerModeButtons" in content, (
            "app-evidence-display.js must define syncLayerModeButtons() and call it whenever "
            "evidenceLayerMode is changed programmatically so buttons match the map"
        )


# ---------------------------------------------------------------------------
# Endpoint auth audit (#572) — ensure every non-anonymous endpoint is protected
# ---------------------------------------------------------------------------


class TestEndpointAuthAudit:
    """Ensure no endpoint that handles user data or triggers actions is unprotected.

    Intentionally anonymous endpoints are documented in ``_EXEMPT_ROUTES``
    with rationale. Everything else must use @require_auth or call check_auth().

    See: https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/572
    """

    # Auth mechanisms that count as "protected"
    _AUTH_PATTERNS: typing.ClassVar[list[str]] = [
        "require_auth",  # @require_auth decorator
        "check_auth",  # check_auth(req) call inside handler body
        "_check_ops_key",  # ops-key header verification
    ]

    # Route patterns that are allowed without user auth
    _EXEMPT_ROUTES: typing.ClassVar[set[str]] = {
        # Intentionally anonymous (documented above)
        "health",
        "readiness",
        "contract",
        # Deep health check — pre-demo smoke probe, no user data, no side effects (#760)
        "health/deep",
        # Internal deploy-only smoke probe (dev orchestrator host restricted)
        "internal-smoke",
        "billing/webhook",
        "contact-form",
        # UUID-gated bearer pattern
        "orchestrator/{instance_id}",
        "timelapse-data/{instance_id}",
        "export/{instance_id}/{format}",
        # Ops-key protected (verified separately)
        "ops/dashboard",
        "ops/users",
        "ops/users/lookup",
        "ops/users/{user_id}/role",
    }

    def test_every_endpoint_is_auth_protected_or_explicitly_exempt(self):
        """Scan all blueprint @bp.route decorators and verify auth coverage.

        Every endpoint must either:
        1. Use @require_auth decorator, OR
        2. Call check_auth() / _check_ops_key() in its body or in a helper
           function within the same file that the handler delegates to, OR
        3. Be listed in _EXEMPT_ROUTES with documented rationale.
        """
        bp_dir = ROOT / "blueprints"
        unprotected = []

        for py_file in sorted(bp_dir.rglob("*.py")):
            if py_file.name.startswith("_"):
                continue
            src = py_file.read_text()

            # Check if any auth pattern appears anywhere in the file.
            # When a route handler delegates to a helper (e.g. _run_analysis)
            # that calls check_auth, the whole file is transitively protected.
            file_has_auth = any(pattern in src for pattern in self._AUTH_PATTERNS)

            # Find all @bp.route(...) declarations and their surrounding context.
            # We parse line-by-line to avoid exponential-backtracking regex (CodeQL).
            lines = src.split("\n")
            i = 0
            while i < len(lines):
                route_m = re.match(r'\s*@bp\.route\(route="([^"]+)"', lines[i])
                if not route_m:
                    i += 1
                    continue

                route = route_m.group(1)
                # Collect decorator block + function body until next route/def/class/EOF
                block_start = i
                i += 1
                # Skip additional decorators
                while i < len(lines) and re.match(r"\s*@\w+", lines[i]):
                    i += 1
                # Skip function signature
                if i < len(lines) and re.match(r"\s*(?:async )?def ", lines[i]):
                    i += 1
                # Collect body until next top-level construct
                while i < len(lines) and not re.match(
                    r"(?:@bp\.|(?:async )?def |class )\S", lines[i]
                ):
                    i += 1
                block = "\n".join(lines[block_start:i])

                if route in self._EXEMPT_ROUTES:
                    continue

                has_auth = any(pattern in block for pattern in self._AUTH_PATTERNS)
                if not has_auth and not file_has_auth:
                    rel = py_file.relative_to(ROOT)
                    unprotected.append(f"{rel}: route='{route}'")

        assert not unprotected, (
            "Endpoints without auth protection and not in _EXEMPT_ROUTES:\n"
            + "\n".join(f"  - {ep}" for ep in unprotected)
            + "\nAdd auth or list in _EXEMPT_ROUTES with rationale."
        )

    def test_retired_demo_routes_are_absent(self):
        """The demo valet/artifact/proxy surface was retired (#922).

        Guards against a regression that re-introduces the anonymous CORS
        proxy or demo valet endpoints. No blueprint may register these routes.
        """
        bp_dir = ROOT / "blueprints"
        retired = {"proxy", "demo-artifacts", "demo-valet-tokens"}
        offenders = []

        for py_file in sorted(bp_dir.rglob("*.py")):
            src = py_file.read_text()
            for route in retired:
                if re.search(rf"""route\s*=\s*["']{re.escape(route)}["']""", src):
                    offenders.append(f"{py_file.relative_to(ROOT)}: route='{route}'")

        assert not offenders, (
            "Retired demo/proxy routes must not be registered (#922):\n"
            + "\n".join(f"  - {o}" for o in offenders)
        )
        assert not (bp_dir / "demo.py").exists(), (
            "blueprints/demo.py was retired in #922 and must not be reintroduced"
        )


# ---------------------------------------------------------------------------
# 16. CIAM app registration under OpenTofu (issue #781/#806/#804)
# ---------------------------------------------------------------------------


class TestCiamTofuOwnership:
    """Ensure the CIAM app registration is progressively brought under Tofu state."""

    @pytest.fixture()
    def main_tf(self):
        return MAIN_TF.read_text()

    @pytest.fixture()
    def variables_tf(self):
        return VARIABLES_TF.read_text()

    @pytest.fixture()
    def locals_tf(self):
        return (INFRA / "locals.tf").read_text()

    def test_ciam_app_registration_resource_declared(self, main_tf):
        """azuread_application_registration.ciam must be declared in main.tf."""
        assert 'resource "azuread_application_registration" "ciam"' in main_tf, (
            "main.tf must declare azuread_application_registration.ciam to bring "
            "the SPA app registration under Tofu state (issue #806)"
        )

    def test_ciam_app_registration_has_import_block(self, main_tf):
        """Import block must be present to adopt the existing registration."""
        assert "azuread_application_registration.ciam" in main_tf, (
            "main.tf must include an import block for azuread_application_registration.ciam "
            "so Tofu adopts the existing app without recreating it (issue #806)"
        )
        # The import block uses for_each so it can be gated conditionally
        assert re.search(
            r"to\s*=\s*azuread_application_registration\.ciam\[each\.key\]",
            main_tf,
        ), (
            "import block for azuread_application_registration.ciam must use for_each "
            "so it is only active when ciam_app_object_id is set"
        )

    def test_ciam_service_principal_resource_declared(self, main_tf):
        """azuread_service_principal.ciam must be declared with use_existing."""
        assert 'resource "azuread_service_principal" "ciam"' in main_tf, (
            "main.tf must declare azuread_service_principal.ciam so the SP is "
            "tracked in state alongside the app registration (issue #806)"
        )
        assert "use_existing = true" in main_tf, (
            "azuread_service_principal.ciam must set use_existing = true to "
            "adopt the existing SP without attempting to recreate it"
        )

    def test_ciam_app_object_id_variable_declared(self, variables_tf):
        """ciam_app_object_id variable must exist with empty default."""
        assert 'variable "ciam_app_object_id"' in variables_tf, (
            "variables.tf must declare ciam_app_object_id so operators can "
            "trigger Phase 2 import by setting it in environments/<env>.tfvars"
        )

    def test_ciam_deploy_app_object_id_variable_declared(self, variables_tf):
        """ciam_deploy_app_object_id variable must exist for federated creds."""
        assert 'variable "ciam_deploy_app_object_id"' in variables_tf, (
            "variables.tf must declare ciam_deploy_app_object_id to enable "
            "Tofu-managed federated identity credentials (issue #804)"
        )

    def test_ciam_deploy_sp_object_id_variable_declared(self, variables_tf):
        """ciam_deploy_sp_object_id variable must exist for owner assertion."""
        assert 'variable "ciam_deploy_sp_object_id"' in variables_tf, (
            "variables.tf must declare ciam_deploy_sp_object_id to enable "
            "Tofu-managed app owner assertion (issue #804)"
        )

    def test_ciam_federated_identity_credential_resource_declared(self, main_tf):
        """azuread_application_federated_identity_credential.ciam_deploy_sp must be declared."""
        assert (
            'resource "azuread_application_federated_identity_credential" "ciam_deploy_sp"'
            in main_tf
        ), (
            "main.tf must declare azuread_application_federated_identity_credential.ciam_deploy_sp "
            "to bring deploy SP OIDC trust under Tofu state (issue #804)"
        )

    def test_ciam_federated_creds_use_correct_issuer(self, main_tf):
        """Federated credentials must use the GitHub Actions OIDC issuer."""
        oidc_issuer = "token.actions.githubusercontent.com"
        assert re.search(
            r'issuer\s*=\s*"https://' + re.escape(oidc_issuer) + r'"',
            main_tf,
        ), (
            "azuread_application_federated_identity_credential must set issuer to "
            f"https://{oidc_issuer} for GitHub Actions OIDC"
        )

    def test_ciam_app_owner_resource_declared(self, main_tf):
        """azuread_application_owner.ciam_deploy_sp must be declared."""
        assert 'resource "azuread_application_owner" "ciam_deploy_sp"' in main_tf, (
            "main.tf must declare azuread_application_owner.ciam_deploy_sp to "
            "assert the deploy SP as owner of the SPA app (issue #804)"
        )

    def test_ciam_app_registration_gated_on_object_id(self, main_tf):
        """Registration resource must be gated when ciam_app_object_id is set."""
        match = re.search(
            r'resource\s+"azuread_application_registration"\s+"ciam"\s*\{(?P<body>.*?)\n\}',
            main_tf,
            re.DOTALL,
        )
        assert match, "main.tf must define azuread_application_registration.ciam"
        body = match.group("body")
        assert "ciam_app_import_enabled" in body or "ciam_app_object_id" in body, (
            "azuread_application_registration.ciam must be gated on ciam_app_object_id "
            "or ciam_app_import_enabled to prevent accidental creation"
        )

    def test_ciam_data_source_kept_as_fallback(self, main_tf):
        """The data source must remain active when ciam_app_object_id is empty."""
        assert 'data "azuread_application" "ciam"' in main_tf, (
            "main.tf must keep data.azuread_application.ciam as a fallback for "
            "Phase 1 (when ciam_app_object_id is not yet set)"
        )

    def test_ciam_app_import_enabled_local_declared(self, locals_tf):
        """ciam_app_import_enabled and ciam_app_id locals must be declared in locals.tf."""
        assert "ciam_app_import_enabled" in locals_tf, (
            "locals.tf must declare ciam_app_import_enabled to gate Phase 2 "
            "resources on ciam_app_object_id being non-empty"
        )
        assert "ciam_app_id" in locals_tf, (
            "locals.tf must declare ciam_app_id to consolidate the Phase 1/2 "
            "application ID reference used by redirect URIs and import block"
        )

    def test_ciam_readme_documents_tofu_ownership(self):
        """README must document the phased Tofu ownership of CIAM resources."""
        readme = (INFRA / "README.md").read_text()
        assert "CIAM Tofu ownership" in readme, (
            "infra/tofu/README.md must document the CIAM Tofu ownership phases (issue #781)"
        )
        assert "ciam_app_object_id" in readme, (
            "infra/tofu/README.md must document the ciam_app_object_id variable "
            "and how to find the object ID"
        )
        assert "Deprecation of manual portal workflow" in readme, (
            "infra/tofu/README.md must explicitly deprecate the manual portal workflow "
            "once Phase 2 is active"
        )


# ---------------------------------------------------------------------------
# 14. CI docs-stub path-filter lockstep guard
# ---------------------------------------------------------------------------


class TestCIDocsStubLockstep:
    """ci-docs-stub.yml paths must stay the exact complement of ci.yml paths-ignore.

    If they drift, a single-file change can trigger both real CI and the stub
    (double check-runs) or trigger neither (protection gap).
    """

    def _load_paths_ignore(self) -> list[str]:
        """Return the paths-ignore list from ci.yml (pull_request trigger)."""
        workflow = yaml.safe_load(CI_YML.read_text())
        # PyYAML parses the bare `on:` key as Python True (YAML boolean)
        pr_trigger = (workflow.get(True) or {}).get("pull_request") or {}
        return sorted(pr_trigger.get("paths-ignore", []))

    def _load_stub_paths(self) -> list[str]:
        """Return the paths list from ci-docs-stub.yml (pull_request trigger)."""
        workflow = yaml.safe_load(CI_DOCS_STUB_YML.read_text())
        pr_trigger = (workflow.get(True) or {}).get("pull_request") or {}
        return sorted(pr_trigger.get("paths", []))

    def test_ci_docs_stub_exists(self):
        assert CI_DOCS_STUB_YML.exists(), (
            "ci-docs-stub.yml must exist to satisfy required check-run contexts on docs-only PRs"
        )

    def test_stub_paths_match_ci_paths_ignore(self):
        """The stub paths filter and ci.yml paths-ignore must be identical.

        Any divergence means at least one file pattern will trigger both
        real CI and the stub simultaneously (ambiguous check-runs) or will
        trigger neither (branch protection gap).
        """
        ci_ignore = self._load_paths_ignore()
        stub_paths = self._load_stub_paths()
        assert ci_ignore == stub_paths, (
            "ci-docs-stub.yml paths and ci.yml paths-ignore have drifted.\n"
            f"  ci.yml paths-ignore:       {ci_ignore}\n"
            f"  ci-docs-stub.yml paths:    {stub_paths}\n"
            "Keep them identical so exactly one of {real CI, stub} runs for "
            "any single-file change."
        )

    def test_push_and_pr_triggers_are_consistent_in_stub(self):
        """push and pull_request triggers in ci-docs-stub.yml must use the same paths."""
        workflow = yaml.safe_load(CI_DOCS_STUB_YML.read_text())
        on = workflow.get(True) or {}
        pr_paths = sorted((on.get("pull_request") or {}).get("paths", []))
        push_paths = sorted((on.get("push") or {}).get("paths", []))
        assert pr_paths == push_paths, (
            "ci-docs-stub.yml pull_request and push triggers must have identical "
            f"paths filters.\n  pull_request: {pr_paths}\n  push: {push_paths}"
        )

    def test_push_and_pr_triggers_are_consistent_in_ci(self):
        """push and pull_request triggers in ci.yml must use the same paths-ignore."""
        workflow = yaml.safe_load(CI_YML.read_text())
        on = workflow.get(True) or {}
        pr_ignore = sorted((on.get("pull_request") or {}).get("paths-ignore", []))
        push_ignore = sorted((on.get("push") or {}).get("paths-ignore", []))
        assert pr_ignore == push_ignore, (
            "ci.yml pull_request and push triggers must have identical "
            f"paths-ignore filters.\n  pull_request: {pr_ignore}\n  push: {push_ignore}"
        )

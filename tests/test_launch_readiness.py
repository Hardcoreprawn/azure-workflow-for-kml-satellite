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
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

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
DEPLOY_YML = ROOT / ".github" / "workflows" / "deploy.yml"
INFRACOST_YML = ROOT / ".github" / "workflows" / "infracost.yml"
INFRACOST_USAGE = INFRA / "infracost-usage.yml"
TRIVY_IGNORE = ROOT / ".trivyignore"
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

    def test_durable_task_logs_are_warning_only(self, host_config):
        levels = host_config["logging"]["logLevel"]
        assert levels["Host.Triggers.DurableTask"] == "Warning", (
            "DurableTask lease-renewal/info chatter must be suppressed "
            "to control Log Analytics cost"
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
        assert "function_app_hostname" in deploy_yml, (
            "deploy.yml smoke check must use function_app_hostname output"
        )
        assert "/api/health" in deploy_yml, (
            "deploy.yml smoke check must test /api/health on the Container Apps FA"
        )
        assert "curl" in deploy_yml, "deploy.yml smoke check must curl the FA health endpoint"

    def test_workflow_dispatch_supports_manual_teardown_rebuild(self, deploy_yml):
        assert "rebuild_after_manual_teardown" in deploy_yml, (
            "deploy.yml manual dispatch must allow rebuilding dev after a manual teardown"
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

    def test_deploy_validates_infra_gate(self, deploy_yml):
        assert "validate_dev_infra_gate.py" in deploy_yml, (
            "deploy.yml must validate the infra gate after reconciliation "
            "so clean-slate redeploy failures stop the job"
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
        assert "&code=${local.eventgrid_key}" in tf, (
            "Event Grid webhook endpointUrl must include the system key query param"
        )


# ---------------------------------------------------------------------------
# 11. Trivy signal quality and exception discipline
# ---------------------------------------------------------------------------


class TestTrivySignalQuality:
    """Ensure Trivy scans stay actionable and exceptions remain explicit."""

    def test_security_trivy_fs_ignores_unfixed(self):
        yml = SECURITY_YML.read_text()
        assert "ignore-unfixed: true" in yml, (
            "security.yml Trivy filesystem scan should ignore unfixed CVEs "
            "to reduce non-actionable alert noise"
        )

    def test_deploy_trivy_image_ignores_unfixed(self):
        yml = DEPLOY_YML.read_text()
        assert "ignore-unfixed: true" in yml, (
            "deploy.yml Trivy image scan should ignore unfixed CVEs "
            "to focus on actionable vulnerabilities"
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

    APP_SHELL = WEBSITE / "js" / "app-shell.js"

    def test_queue_error_branch_resets_progress(self):
        """Error branches in queueAnalysis must call resetAnalysisProgress()."""
        content = self.APP_SHELL.read_text()
        # Find the queueAnalysis function
        fn_start = content.find("async function queueAnalysis()")
        assert fn_start != -1, "queueAnalysis function not found in app-shell.js"

        # Extract until next top-level function (heuristic: next 'async function' or '  function')
        fn_end = content.find("\n  async function ", fn_start + 1)
        if fn_end == -1:
            fn_end = len(content)
        fn_body = content[fn_start:fn_end]

        # Find error handling blocks: 'if (!tokenRes || !tokenRes.ok)' or
        # 'if (!uploadRes || !uploadRes.ok)' — the event-driven flow has
        # two error check points (token + upload)
        error_branch = re.search(
            r"if\s*\(\s*!\w+Res\s*\|\|\s*!\w+Res\.ok\s*\)(.*?)(?:}\s*$|}\s*\n)",
            fn_body,
            flags=re.DOTALL,
        )
        assert error_branch, "Error branch 'if (!...Res || !...Res.ok)' not found in queueAnalysis"
        error_block = error_branch.group(1)

        assert "resetAnalysisProgress" in error_block, (
            "queueAnalysis error branch must call resetAnalysisProgress() "
            "to hide the pipeline spinner on API failure"
        )


# ---------------------------------------------------------------------------
# 13. Infracost cost-gate workflow and usage file
# ---------------------------------------------------------------------------


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

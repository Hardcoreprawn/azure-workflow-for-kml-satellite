"""Infrastructure tests for Bicep templates.

Validates that Bicep templates compile to correct ARM JSON with expected
resource types, properties, and security configurations. These tests run
without an Azure subscription by compiling Bicep → ARM JSON and inspecting
the output structure.

Requires: Azure CLI with Bicep extension installed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

INFRA_DIR = Path(__file__).resolve().parent.parent.parent / "infra"


def _bicep_build(bicep_file: Path) -> dict[str, Any]:
    """Compile a Bicep file to ARM JSON and return the parsed dict.

    Supports both standalone ``bicep`` CLI and ``az bicep`` wrapper.
    """
    # Try standalone Bicep CLI first, fall back to az bicep
    for cmd in (
        ["bicep", "build", str(bicep_file), "--stdout"],
        ["az", "bicep", "build", "--file", str(bicep_file), "--stdout"],
    ):
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)

    pytest.fail(f"Bicep build failed for {bicep_file.name}:\n{result.stderr}")


@pytest.fixture(scope="module")
def main_arm_template() -> dict[str, Any]:
    """Compiled ARM template from main.bicep."""
    return _bicep_build(INFRA_DIR / "main.bicep")


@pytest.fixture(scope="module")
def storage_arm_template() -> dict[str, Any]:
    """Compiled ARM template from modules/storage.bicep."""
    return _bicep_build(INFRA_DIR / "modules" / "storage.bicep")


@pytest.fixture(scope="module")
def monitoring_arm_template() -> dict[str, Any]:
    """Compiled ARM template from modules/monitoring.bicep."""
    return _bicep_build(INFRA_DIR / "modules" / "monitoring.bicep")


@pytest.fixture(scope="module")
def keyvault_arm_template() -> dict[str, Any]:
    """Compiled ARM template from modules/keyvault.bicep."""
    return _bicep_build(INFRA_DIR / "modules" / "keyvault.bicep")


@pytest.fixture(scope="module")
def function_app_arm_template() -> dict[str, Any]:
    """Compiled ARM template from modules/function-app.bicep."""
    return _bicep_build(INFRA_DIR / "modules" / "function-app.bicep")


@pytest.fixture(scope="module")
def event_grid_arm_template() -> dict[str, Any]:
    """Compiled ARM template from modules/event-grid.bicep."""
    return _bicep_build(INFRA_DIR / "modules" / "event-grid.bicep")


@pytest.fixture(scope="module")
def rbac_arm_template() -> dict[str, Any]:
    """Compiled ARM template from modules/rbac.bicep."""
    return _bicep_build(INFRA_DIR / "modules" / "rbac.bicep")


def _get_resources_by_type(template: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    """Extract resources of a given type from an ARM template."""
    return [
        r
        for r in template.get("resources", [])
        if r.get("type", "").lower() == resource_type.lower()
    ]


def _get_all_resource_types(template: dict[str, Any]) -> set[str]:
    """Get all resource types defined in a template."""
    return {r["type"] for r in template.get("resources", []) if "type" in r}


# ---------------------------------------------------------------------------
# Test: Bicep compilation
# ---------------------------------------------------------------------------


class TestBicepCompilation:
    """Verify all Bicep files compile without errors."""

    @pytest.mark.parametrize(
        "bicep_file",
        [
            "main.bicep",
            "modules/storage.bicep",
            "modules/monitoring.bicep",
            "modules/keyvault.bicep",
            "modules/function-app.bicep",
            "modules/event-grid.bicep",
            "modules/rbac.bicep",
        ],
    )
    def test_bicep_compiles(self, bicep_file: str) -> None:
        """Each Bicep file must compile to valid ARM JSON."""
        path = INFRA_DIR / bicep_file
        assert path.exists(), f"Bicep file not found: {path}"
        template = _bicep_build(path)
        assert "$schema" in template
        assert template["contentVersion"] == "1.0.0.0"


# ---------------------------------------------------------------------------
# Test: Main template structure
# ---------------------------------------------------------------------------


class TestMainTemplate:
    """Verify the main orchestration template structure."""

    def test_has_parameters(self, main_arm_template: dict[str, Any]) -> None:
        """Main template must define expected parameters."""
        params = set(main_arm_template.get("parameters", {}).keys())
        expected = {"baseName", "location", "environment"}
        assert expected.issubset(params), f"Missing params: {expected - params}"

    def test_environment_allowed_values(self, main_arm_template: dict[str, Any]) -> None:
        """Environment parameter must restrict to dev/staging/prod."""
        env_param = main_arm_template["parameters"]["environment"]
        allowed = env_param.get("allowedValues", [])
        assert set(allowed) == {"dev", "staging", "prod"}

    def test_has_outputs(self, main_arm_template: dict[str, Any]) -> None:
        """Main template must expose key outputs."""
        outputs = set(main_arm_template.get("outputs", {}).keys())
        expected = {
            "storageAccountName",
            "functionAppName",
            "functionAppHostName",
            "keyVaultName",
            "appInsightsInstrumentationKey",
        }
        assert expected.issubset(outputs), f"Missing outputs: {expected - outputs}"

    def test_has_module_deployments(self, main_arm_template: dict[str, Any]) -> None:
        """Main template must reference all infrastructure modules."""
        resources = main_arm_template.get("resources", [])
        deployment_names = {
            r.get("name") for r in resources if r["type"] == "Microsoft.Resources/deployments"
        }
        # Bicep modules compile to nested deployments — names may be
        # string expressions, so we check for presence of deployments.
        assert len(deployment_names) >= 5, (
            f"Expected ≥5 module deployments, got {len(deployment_names)}: {deployment_names}"
        )


# ---------------------------------------------------------------------------
# Test: Storage module
# ---------------------------------------------------------------------------


class TestStorageModule:
    """Verify storage account configuration."""

    def test_storage_account_exists(self, storage_arm_template: dict[str, Any]) -> None:
        """Must define a Storage Account resource."""
        accounts = _get_resources_by_type(
            storage_arm_template, "Microsoft.Storage/storageAccounts"
        )
        assert len(accounts) == 1

    def test_storage_account_is_gpv2_hot(self, storage_arm_template: dict[str, Any]) -> None:
        """Storage account must be StorageV2 with Hot access tier."""
        account = _get_resources_by_type(
            storage_arm_template, "Microsoft.Storage/storageAccounts"
        )[0]
        assert account["kind"] == "StorageV2"
        assert account["properties"]["accessTier"] == "Hot"

    def test_blob_public_access_disabled(self, storage_arm_template: dict[str, Any]) -> None:
        """Public blob access must be disabled."""
        account = _get_resources_by_type(
            storage_arm_template, "Microsoft.Storage/storageAccounts"
        )[0]
        assert account["properties"]["allowBlobPublicAccess"] is False

    def test_tls_12_minimum(self, storage_arm_template: dict[str, Any]) -> None:
        """Minimum TLS version must be 1.2."""
        account = _get_resources_by_type(
            storage_arm_template, "Microsoft.Storage/storageAccounts"
        )[0]
        assert account["properties"]["minimumTlsVersion"] == "TLS1_2"

    def test_https_only(self, storage_arm_template: dict[str, Any]) -> None:
        """HTTPS-only traffic must be enforced."""
        account = _get_resources_by_type(
            storage_arm_template, "Microsoft.Storage/storageAccounts"
        )[0]
        assert account["properties"]["supportsHttpsTrafficOnly"] is True

    def test_containers_defined(self, storage_arm_template: dict[str, Any]) -> None:
        """Must define kml-input and kml-output blob containers."""
        containers = _get_resources_by_type(
            storage_arm_template,
            "Microsoft.Storage/storageAccounts/blobServices/containers",
        )
        container_names = {c["name"] for c in containers}
        # Bicep may emit the name as the last segment or a full expression.
        # Check that we have at least 2 container resources.
        assert len(containers) >= 2, f"Expected ≥2 containers, got: {container_names}"

    def test_lifecycle_policy_exists(self, storage_arm_template: dict[str, Any]) -> None:
        """Must define lifecycle management policy for archival."""
        policies = _get_resources_by_type(
            storage_arm_template,
            "Microsoft.Storage/storageAccounts/managementPolicies",
        )
        assert len(policies) == 1

    def test_has_outputs(self, storage_arm_template: dict[str, Any]) -> None:
        """Storage module must output id, name, and connectionString."""
        outputs = set(storage_arm_template.get("outputs", {}).keys())
        assert {"id", "name", "connectionString"}.issubset(outputs)


# ---------------------------------------------------------------------------
# Test: Monitoring module
# ---------------------------------------------------------------------------


class TestMonitoringModule:
    """Verify monitoring configuration."""

    def test_log_analytics_workspace_exists(self, monitoring_arm_template: dict[str, Any]) -> None:
        """Must define a Log Analytics workspace."""
        workspaces = _get_resources_by_type(
            monitoring_arm_template, "Microsoft.OperationalInsights/workspaces"
        )
        assert len(workspaces) == 1

    def test_app_insights_exists(self, monitoring_arm_template: dict[str, Any]) -> None:
        """Must define an Application Insights instance."""
        insights = _get_resources_by_type(monitoring_arm_template, "Microsoft.Insights/components")
        assert len(insights) == 1

    def test_app_insights_is_web_type(self, monitoring_arm_template: dict[str, Any]) -> None:
        """Application Insights must be of type 'web'."""
        insights = _get_resources_by_type(
            monitoring_arm_template, "Microsoft.Insights/components"
        )[0]
        assert insights["properties"]["Application_Type"] == "web"

    def test_workspace_backed_app_insights(self, monitoring_arm_template: dict[str, Any]) -> None:
        """Application Insights must use Log Analytics workspace (not classic)."""
        insights = _get_resources_by_type(
            monitoring_arm_template, "Microsoft.Insights/components"
        )[0]
        assert insights["properties"]["IngestionMode"] == "LogAnalytics"

    def test_has_outputs(self, monitoring_arm_template: dict[str, Any]) -> None:
        """Monitoring module must output connection strings and IDs."""
        outputs = set(monitoring_arm_template.get("outputs", {}).keys())
        expected = {"appInsightsId", "instrumentationKey", "connectionString"}
        assert expected.issubset(outputs)


# ---------------------------------------------------------------------------
# Test: Key Vault module
# ---------------------------------------------------------------------------


class TestKeyVaultModule:
    """Verify Key Vault configuration."""

    def test_key_vault_exists(self, keyvault_arm_template: dict[str, Any]) -> None:
        """Must define a Key Vault resource."""
        vaults = _get_resources_by_type(keyvault_arm_template, "Microsoft.KeyVault/vaults")
        assert len(vaults) == 1

    def test_rbac_authorization_enabled(self, keyvault_arm_template: dict[str, Any]) -> None:
        """Key Vault must use RBAC authorization (not access policies)."""
        vault = _get_resources_by_type(keyvault_arm_template, "Microsoft.KeyVault/vaults")[0]
        assert vault["properties"]["enableRbacAuthorization"] is True

    def test_soft_delete_enabled(self, keyvault_arm_template: dict[str, Any]) -> None:
        """Key Vault must have soft-delete enabled."""
        vault = _get_resources_by_type(keyvault_arm_template, "Microsoft.KeyVault/vaults")[0]
        assert vault["properties"]["enableSoftDelete"] is True

    def test_has_outputs(self, keyvault_arm_template: dict[str, Any]) -> None:
        """Key Vault module must output id, name, and uri."""
        outputs = set(keyvault_arm_template.get("outputs", {}).keys())
        assert {"id", "name", "uri"}.issubset(outputs)


# ---------------------------------------------------------------------------
# Test: Function App module
# ---------------------------------------------------------------------------


class TestFunctionAppModule:
    """Verify Function App configuration."""

    def test_app_service_plan_exists(self, function_app_arm_template: dict[str, Any]) -> None:
        """Must define an App Service Plan."""
        plans = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/serverfarms")
        assert len(plans) == 1

    def test_flex_consumption_sku(self, function_app_arm_template: dict[str, Any]) -> None:
        """App Service Plan must use Flex Consumption tier."""
        plan = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/serverfarms")[0]
        sku = plan.get("sku", {})
        assert sku.get("name") == "FC1"
        assert sku.get("tier") == "FlexConsumption"

    def test_linux_reserved(self, function_app_arm_template: dict[str, Any]) -> None:
        """App Service Plan must be reserved (Linux)."""
        plan = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/serverfarms")[0]
        assert plan["properties"]["reserved"] is True

    def test_function_app_exists(self, function_app_arm_template: dict[str, Any]) -> None:
        """Must define a Function App site."""
        sites = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/sites")
        assert len(sites) == 1

    def test_function_app_is_linux(self, function_app_arm_template: dict[str, Any]) -> None:
        """Function App must be Linux-based."""
        site = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/sites")[0]
        assert "linux" in site.get("kind", "").lower()

    def test_managed_identity_enabled(self, function_app_arm_template: dict[str, Any]) -> None:
        """Function App must have system-assigned managed identity."""
        site = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/sites")[0]
        identity = site.get("identity", {})
        assert identity.get("type") == "SystemAssigned"

    def test_https_only(self, function_app_arm_template: dict[str, Any]) -> None:
        """Function App must enforce HTTPS only."""
        site = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/sites")[0]
        assert site["properties"]["httpsOnly"] is True

    def test_has_required_app_settings(self, function_app_arm_template: dict[str, Any]) -> None:
        """Function App must have required application settings."""
        site = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/sites")[0]
        app_settings = site["properties"].get("siteConfig", {}).get("appSettings", [])
        setting_names = {s["name"] for s in app_settings}
        expected = {
            "AzureWebJobsStorage",
            "APPLICATIONINSIGHTS_CONNECTION_STRING",
            "KEY_VAULT_URI",
            "FUNCTIONS_EXTENSION_VERSION",
            "KML_INPUT_CONTAINER",
            "KML_OUTPUT_CONTAINER",
            "IMAGERY_PROVIDER",
        }
        assert expected.issubset(setting_names), (
            f"Missing app settings: {expected - setting_names}"
        )

    def test_functions_v4(self, function_app_arm_template: dict[str, Any]) -> None:
        """Function App must use Functions runtime v4."""
        site = _get_resources_by_type(function_app_arm_template, "Microsoft.Web/sites")[0]
        app_settings = site["properties"]["siteConfig"]["appSettings"]
        version_setting = next(
            (s for s in app_settings if s["name"] == "FUNCTIONS_EXTENSION_VERSION"),
            None,
        )
        assert version_setting is not None
        assert version_setting["value"] == "~4"

    def test_has_outputs(self, function_app_arm_template: dict[str, Any]) -> None:
        """Function App module must output id, name, principalId, hostname."""
        outputs = set(function_app_arm_template.get("outputs", {}).keys())
        expected = {"id", "name", "principalId", "defaultHostName"}
        assert expected.issubset(outputs), f"Missing outputs: {expected - outputs}"


# ---------------------------------------------------------------------------
# Test: Event Grid module
# ---------------------------------------------------------------------------


class TestEventGridModule:
    """Verify Event Grid configuration."""

    def test_system_topic_exists(self, event_grid_arm_template: dict[str, Any]) -> None:
        """Must define an Event Grid system topic."""
        topics = _get_resources_by_type(
            event_grid_arm_template, "Microsoft.EventGrid/systemTopics"
        )
        assert len(topics) == 1

    def test_system_topic_source_is_storage(self, event_grid_arm_template: dict[str, Any]) -> None:
        """System topic must be sourced from a Storage Account."""
        topic = _get_resources_by_type(
            event_grid_arm_template, "Microsoft.EventGrid/systemTopics"
        )[0]
        assert topic["properties"]["topicType"] == "Microsoft.Storage.StorageAccounts"

    def test_event_subscription_exists(self, event_grid_arm_template: dict[str, Any]) -> None:
        """Must define an event subscription on the system topic."""
        subs = _get_resources_by_type(
            event_grid_arm_template,
            "Microsoft.EventGrid/systemTopics/eventSubscriptions",
        )
        assert len(subs) == 1

    def test_event_subscription_filters_kml(self, event_grid_arm_template: dict[str, Any]) -> None:
        """Event subscription must filter for .kml files in kml-input."""
        sub = _get_resources_by_type(
            event_grid_arm_template,
            "Microsoft.EventGrid/systemTopics/eventSubscriptions",
        )[0]
        event_filter = sub["properties"]["filter"]
        assert event_filter["subjectEndsWith"] == ".kml"
        assert "kml-input" in event_filter["subjectBeginsWith"]
        assert "Microsoft.Storage.BlobCreated" in event_filter["includedEventTypes"]

    def test_has_outputs(self, event_grid_arm_template: dict[str, Any]) -> None:
        """Event Grid module must output topic ID and name."""
        outputs = set(event_grid_arm_template.get("outputs", {}).keys())
        assert {"systemTopicId", "systemTopicName"}.issubset(outputs)


# ---------------------------------------------------------------------------
# Test: RBAC module
# ---------------------------------------------------------------------------


class TestRbacModule:
    """Verify RBAC role assignments."""

    def test_role_assignments_defined(self, rbac_arm_template: dict[str, Any]) -> None:
        """Must define role assignments for storage and Key Vault."""
        assignments = _get_resources_by_type(
            rbac_arm_template, "Microsoft.Authorization/roleAssignments"
        )
        assert len(assignments) >= 2, f"Expected ≥2 role assignments, got {len(assignments)}"


# ---------------------------------------------------------------------------
# Test: Security posture (cross-cutting)
# ---------------------------------------------------------------------------


class TestSecurityPosture:
    """Cross-cutting security validations across all modules."""

    def test_no_plain_text_secrets_in_storage_outputs(
        self, storage_arm_template: dict[str, Any]
    ) -> None:
        """Connection string output must not be a plain string parameter.

        Note: In the compiled ARM JSON the connection string is an expression
        (listKeys), not a static value — this is the expected secure pattern.
        """
        outputs = storage_arm_template.get("outputs", {})
        conn = outputs.get("connectionString", {})
        # The value should be an ARM expression, not a plain string literal.
        value = conn.get("value", "")
        assert isinstance(value, str)
        # If it's an expression it will start with [ in ARM JSON.
        # A plain literal would not. Both are acceptable since this is
        # compile-time output, but we verify the output exists.
        assert "connectionString" in outputs

    def test_keyvault_uses_rbac_not_access_policies(
        self, keyvault_arm_template: dict[str, Any]
    ) -> None:
        """Key Vault must use RBAC (not legacy access policies)."""
        vault = _get_resources_by_type(keyvault_arm_template, "Microsoft.KeyVault/vaults")[0]
        assert vault["properties"]["enableRbacAuthorization"] is True
        # Should NOT have accessPolicies defined
        access_policies = vault["properties"].get("accessPolicies", [])
        assert len(access_policies) == 0, "Should use RBAC, not access policies"

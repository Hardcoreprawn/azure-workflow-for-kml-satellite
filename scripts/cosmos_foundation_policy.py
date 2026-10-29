"""Fail-closed policy over actual native plans where Trivy lacks AzAPI coverage."""

from __future__ import annotations

from scripts.application_contract import ContractError, encode

COSMOS_CONTAINERS = {
    "runs": (
        "/user_id",
        ("/submitted_at/?", "/status/?"),
        ((("/submitted_at", "descending"), ("/status", "ascending")),),
    ),
    "subscriptions": ("/user_id", ("/status/?", "/stripe_customer_id/?"), ()),
    "users": ("/user_id", ("/email/?",), ()),
    "monitors": (
        "/user_id",
        ("/enabled/?", "/next_check_at/?", "/created_at/?"),
        ((("/enabled", "ascending"), ("/next_check_at", "ascending")),),
    ),
    "catalogue": (
        "/user_id",
        ("/submitted_at/?", "/aoi_name/?", "/status/?", "/run_id/?", "/provider/?"),
        (
            (("/submitted_at", "descending"), ("/status", "ascending")),
            (("/aoi_name", "ascending"), ("/submitted_at", "descending")),
        ),
    ),
    "orgs": ("/org_id", ("/doc_type/?", "/members/[]/user_id/?", "/created_at/?"), ()),
    "feature_flags": ("/feature_name", ("/status/?", "/kill_switch/?"), ()),
    "feature_flag_overrides": ("/user_id", ("/user_id/?",), ()),
}
COSMOS_INVENTORY = {
    "azapi_resource.cosmos",
    "azurerm_user_assigned_identity.cosmos_cmk",
    "azurerm_key_vault_key.cosmos_cmk",
    "azurerm_cosmosdb_sql_database.main",
    "azurerm_monitor_diagnostic_setting.cosmos",
    *(f"azurerm_cosmosdb_sql_container.{name}" for name in COSMOS_CONTAINERS),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(f"Cosmos native policy: {message}")


def validate_cosmos_provider(providers: dict) -> None:
    expressions = providers.get("azapi", {}).get("expressions", {})
    for field, value in {
        "use_oidc": True,
        "use_cli": False,
        "use_msi": False,
        "skip_provider_registration": True,
        "disable_default_output": True,
        "enable_preflight": False,
    }.items():
        require(expressions.get(field, {}).get("constant_value") is value, f"explicit AzAPI {field}={value}")
    for field in ("client_id", "tenant_id", "subscription_id"):
        expected = f"local.context.foundation.{field}" if field == "client_id" else f"local.context.{field}"
        require(expected in expressions.get(field, {}).get("references", []), f"AzAPI approved {field}")
    require(
        set(expressions)
        == {
            "subscription_id",
            "tenant_id",
            "client_id",
            "use_oidc",
            "use_cli",
            "use_msi",
            "skip_provider_registration",
            "disable_default_output",
            "enable_preflight",
        },
        "no provider credentials or unapproved authentication paths",
    )


def validate_cosmos_resources(resources: list[dict], phase: str) -> None:
    if phase not in ("cosmos-key", "cosmos"):
        return
    values = {item["address"].split("[")[0]: item.get("values", {}) for item in resources}
    key = values["azurerm_key_vault_key.cosmos_cmk"]
    require(key["name"] == "cosmos-cmk" and key["key_type"] == "RSA" and key["key_size"] == 2048, "dedicated RSA key")
    require(set(key["key_opts"]) == {"unwrapKey", "wrapKey"}, "key operations")
    rotation = key["rotation_policy"][0]
    require(
        rotation["expire_after"] == "P180D"
        and rotation["notify_before_expiry"] == "P30D"
        and rotation["automatic"][0]["time_after_creation"] == "P90D",
        "key rotation defaults",
    )
    if phase == "cosmos":
        _account(values)
        _containers(values)


def _account(values: dict) -> None:
    account = values["azapi_resource.cosmos"]
    identity = values["azurerm_user_assigned_identity.cosmos_cmk"]
    key = values["azurerm_key_vault_key.cosmos_cmk"]
    require(account["type"] == "Microsoft.DocumentDB/databaseAccounts@2024-11-15", "pinned ARM API")
    require(account["schema_validation_enabled"] is True, "embedded ARM schema validation enabled")
    require(account["response_export_values"] == ["properties.documentEndpoint"], "only endpoint exported")
    require(
        account["identity"][0]["type"] == "UserAssigned" and account["identity"][0]["identity_ids"] == [identity["id"]],
        "dedicated identity attachment",
    )
    body = account["body"]
    require(set(body) == {"kind", "properties"} and body["kind"] == "GlobalDocumentDB", "NoSQL account body")
    expected = {
        "databaseAccountOfferType": "Standard",
        "capabilities": [{"name": "EnableServerless"}],
        "consistencyPolicy": {"defaultConsistencyLevel": "Session"},
        "locations": [{"locationName": account["location"], "failoverPriority": 0, "isZoneRedundant": False}],
        "enableAutomaticFailover": False,
        "enableMultipleWriteLocations": False,
        "disableLocalAuth": True,
        "disableKeyBasedMetadataWriteAccess": True,
        "publicNetworkAccess": "Disabled",
        "networkAclBypass": "None",
        "networkAclBypassResourceIds": [],
        "ipRules": [],
        "virtualNetworkRules": [],
        "minimalTlsVersion": "Tls12",
        "backupPolicy": {"type": "Continuous", "continuousModeProperties": {"tier": "Continuous7Days"}},
        "keyVaultKeyUri": key["versionless_id"],
        "defaultIdentity": f"UserAssignedIdentity={identity['id']}",
    }
    require(encode(body["properties"]) == encode(expected), "exact approved account properties")
    diagnostic = values["azurerm_monitor_diagnostic_setting.cosmos"]
    require(
        diagnostic["target_resource_id"] == account["id"]
        and diagnostic["log_analytics_workspace_id"] == values["azurerm_log_analytics_workspace.main"]["id"],
        "existing restricted audit sink",
    )
    require(
        [log["category"] for log in diagnostic["enabled_log"]] == ["ControlPlaneRequests"]
        and not diagnostic.get("enabled_metric"),
        "control-plane logs only",
    )


def _containers(values: dict) -> None:
    database = values["azurerm_cosmosdb_sql_database.main"]
    require(
        database["name"] == "treesight" and database["account_name"] == values["azapi_resource.cosmos"]["name"],
        "database ancestry",
    )
    require(database.get("throughput") == 0 and not database.get("autoscale_settings"), "serverless database")
    for name, (partition, included, composites) in COSMOS_CONTAINERS.items():
        item = values[f"azurerm_cosmosdb_sql_container.{name}"]
        require(
            item["name"] == name
            and item["database_name"] == database["name"]
            and item["account_name"] == database["account_name"],
            f"{name} ancestry",
        )
        require(
            item["partition_key_paths"] == [partition] and item["partition_key_version"] is None, f"{name} partition"
        )
        require(item.get("default_ttl") == (-1 if name == "runs" else None), f"{name} TTL")
        require(item.get("throughput") == 0 and not item.get("autoscale_settings"), f"{name} serverless")
        policy = item["indexing_policy"][0]
        require(
            policy["indexing_mode"] == "consistent"
            and {path["path"] for path in policy["included_path"]} == set(included)
            and [path["path"] for path in policy["excluded_path"]] == ["/*"],
            f"{name} indexes",
        )
        actual = tuple(
            tuple((index["path"], index["order"]) for index in group["index"]) for group in policy["composite_index"]
        )
        require(actual == composites and not policy.get("spatial_index"), f"{name} composite indexes")

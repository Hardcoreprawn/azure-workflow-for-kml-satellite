"""Unit tests of policy rejection; scanner evidence uses only actual native plans."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.application_contract import ContractError
from scripts.cosmos_foundation_policy import COSMOS_CONTAINERS, validate_cosmos_resources


def resources() -> list[dict]:
    path = Path(__file__).parent / "fixtures/foundation/dev/cosmos-manifest.json"
    manifest = json.loads(path.read_bytes())
    cosmos = manifest["cosmos"]
    identity_id = cosmos["encryption"]["identity_id"]
    values = {
        "azurerm_user_assigned_identity.cosmos_cmk": {"id": identity_id},
        "azurerm_key_vault_key.cosmos_cmk": {
            "name": "cosmos-cmk",
            "key_type": "RSA",
            "key_size": 2048,
            "key_opts": ["wrapKey", "unwrapKey"],
            "versionless_id": cosmos["encryption"]["key_uri"],
            "rotation_policy": [
                {
                    "expire_after": "P180D",
                    "notify_before_expiry": "P30D",
                    "automatic": [{"time_after_creation": "P90D"}],
                }
            ],
        },
        "azurerm_log_analytics_workspace.main": {"id": manifest["audit"]["workspace_id"]},
        "azurerm_monitor_diagnostic_setting.cosmos": {
            "target_resource_id": cosmos["id"],
            "log_analytics_workspace_id": manifest["audit"]["workspace_id"],
            "enabled_log": [{"category": "ControlPlaneRequests"}],
            "enabled_metric": [],
        },
        "azurerm_cosmosdb_sql_database.main": {
            "name": "treesight",
            "account_name": cosmos["name"],
            "throughput": 0,
            "autoscale_settings": [],
        },
        "azapi_resource.cosmos": {
            "id": cosmos["id"],
            "name": cosmos["name"],
            "location": "westeurope",
            "type": "Microsoft.DocumentDB/databaseAccounts@2024-11-15",
            "schema_validation_enabled": True,
            "response_export_values": ["properties.documentEndpoint"],
            "identity": [{"type": "UserAssigned", "identity_ids": [identity_id]}],
            "body": {
                "kind": "GlobalDocumentDB",
                "properties": {
                    "databaseAccountOfferType": "Standard",
                    "capabilities": [{"name": "EnableServerless"}],
                    "consistencyPolicy": {"defaultConsistencyLevel": "Session"},
                    "locations": [{"locationName": "westeurope", "failoverPriority": 0, "isZoneRedundant": False}],
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
                    "keyVaultKeyUri": cosmos["encryption"]["key_uri"],
                    "defaultIdentity": f"UserAssignedIdentity={identity_id}",
                },
            },
        },
    }
    for name, (partition, included, composites) in COSMOS_CONTAINERS.items():
        values[f"azurerm_cosmosdb_sql_container.{name}"] = {
            "name": name,
            "database_name": "treesight",
            "account_name": cosmos["name"],
            "partition_key_paths": [partition],
            "partition_key_version": None,
            "default_ttl": -1 if name == "runs" else None,
            "throughput": 0,
            "autoscale_settings": [],
            "indexing_policy": [
                {
                    "indexing_mode": "consistent",
                    "included_path": [{"path": path} for path in included],
                    "excluded_path": [{"path": "/*"}],
                    "composite_index": [
                        {"index": [{"path": path, "order": order} for path, order in composite]}
                        for composite in composites
                    ],
                    "spatial_index": [],
                }
            ],
        }
    return [{"address": f"{address}[0]", "values": value} for address, value in values.items()]


def test_native_policy_is_pure_and_preserves_partial_phases() -> None:
    items = resources()
    before = deepcopy(items)
    for phase in ("prerequisites", "key", "storage", "cosmos-key", "cosmos"):
        validate_cosmos_resources(items, phase)
    assert items == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("disableLocalAuth", False),
        ("disableLocalAuth", 1),
        ("disableKeyBasedMetadataWriteAccess", False),
        ("publicNetworkAccess", "Enabled"),
        ("networkAclBypass", "AzureServices"),
        ("networkAclBypassResourceIds", ["foreign"]),
        ("ipRules", [{"ipAddressOrRange": "0.0.0.0"}]),
        ("capabilities", []),
        ("consistencyPolicy", {"defaultConsistencyLevel": "Eventual"}),
        ("backupPolicy", {"type": "Periodic"}),
        ("minimalTlsVersion", "Tls"),
        ("defaultIdentity", "FirstPartyIdentity"),
        ("keyVaultKeyUri", "foreign"),
        ("restoreParameters", {"restoreSource": "foreign"}),
    ],
)
def test_native_policy_rejects_account_body_mutations(field: str, value: object) -> None:
    items = resources()
    account = next(item["values"] for item in items if item["address"] == "azapi_resource.cosmos[0]")
    account["body"]["properties"][field] = value
    with pytest.raises(ContractError, match="account properties"):
        validate_cosmos_resources(items, "cosmos")


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_validation_enabled", False),
        ("response_export_values", ["*"]),
        ("type", "Microsoft.DocumentDB/databaseAccounts@2025-01-01"),
        ("identity", [{"type": "SystemAssigned", "identity_ids": []}]),
        ("body", {"kind": "MongoDB", "properties": {}}),
    ],
)
def test_native_policy_rejects_account_provider_mutations(field: str, value: object) -> None:
    items = resources()
    account = next(item["values"] for item in items if item["address"] == "azapi_resource.cosmos[0]")
    account[field] = value
    with pytest.raises(ContractError):
        validate_cosmos_resources(items, "cosmos")


@pytest.mark.parametrize(
    "field,value",
    [
        ("partition_key_paths", ["/tenant_id"]),
        ("partition_key_version", 2),
        ("default_ttl", 30),
        ("throughput", 400),
        ("name", "pipeline_stats"),
        (
            "indexing_policy",
            [
                {
                    "indexing_mode": "none",
                    "included_path": [],
                    "excluded_path": [{"path": "/*"}],
                    "composite_index": [],
                    "spatial_index": [],
                }
            ],
        ),
    ],
)
def test_native_policy_rejects_container_schema_or_capacity_changes(field: str, value: object) -> None:
    items = resources()
    container = next(item["values"] for item in items if item["address"] == "azurerm_cosmosdb_sql_container.runs[0]")
    container[field] = value
    with pytest.raises(ContractError):
        validate_cosmos_resources(items, "cosmos")


@pytest.mark.parametrize("category", ["QueryRuntimeStatistics", "DataPlaneRequests", "PartitionKeyStatistics"])
def test_native_policy_rejects_data_plane_and_query_logs(category: str) -> None:
    items = resources()
    diagnostic = next(item["values"] for item in items if item["address"].startswith("azurerm_monitor_diagnostic"))
    diagnostic["enabled_log"] = [{"category": category}]
    with pytest.raises(ContractError, match="control-plane logs only"):
        validate_cosmos_resources(items, "cosmos")

mock_provider "azurerm" {}
mock_provider "random" {}
mock_provider "azapi" {}

override_resource {
  target = azurerm_user_assigned_identity.cosmos_cmk[0]
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-dev-application-cosmos-encryption"
    client_id    = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    principal_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
  }
}
override_resource {
  target = azurerm_key_vault_key.cosmos_cmk[0]
  values = {
    resource_versionless_id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.KeyVault/vaults/akmlsatdevvabc123/keys/cosmos-cmk"
    versionless_id          = "https://akmlsatdevvabc123.vault.azure.net/keys/cosmos-cmk"
  }
}
override_resource {
  target = azapi_resource.cosmos[0]
  values = {
    id     = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application"
    output = { properties = { documentEndpoint = "https://cosmos-kmlsat-dev-application.documents.azure.com:443/" } }
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_database.main[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.runs[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/runs"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.subscriptions[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/subscriptions"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.users[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/users"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.monitors[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/monitors"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.catalogue[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/catalogue"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.orgs[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/orgs"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.feature_flags[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/feature_flags"
  }
}
override_resource {
  target = azurerm_cosmosdb_sql_container.feature_flag_overrides[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-kmlsat-dev-application/sqlDatabases/treesight/containers/feature_flag_overrides"
  }
}

override_resource {
  target = random_string.storage_suffix
  values = { result = "abc123" }
}
override_resource {
  target = azurerm_user_assigned_identity.storage_cmk
  values = {
    id           = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-kmlsat-dev-application-encryption"
    client_id    = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    principal_id = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"
  }
}
override_resource {
  target = azurerm_log_analytics_workspace.main
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.OperationalInsights/workspaces/law-kmlsat-dev-application"
  }
}
override_resource {
  target = azurerm_key_vault_key.storage_cmk[0]
  values = {
    resource_versionless_id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.KeyVault/vaults/akmlsatdevvabc123/keys/application-cmk"
    versionless_id          = "https://akmlsatdevvabc123.vault.azure.net/keys/application-cmk"
  }
}
override_resource {
  target = azurerm_storage_account.main[0]
  values = {
    id                    = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.Storage/storageAccounts/kmlsatdevappabc123"
    primary_blob_endpoint = "https://kmlsatdevappabc123.blob.core.windows.net/"
  }
}
override_resource {
  target = azurerm_storage_container.kml_input[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.Storage/storageAccounts/kmlsatdevappabc123/blobServices/default/containers/kml-input"
  }
}
override_resource {
  target = azurerm_storage_container.kml_output[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.Storage/storageAccounts/kmlsatdevappabc123/blobServices/default/containers/kml-output"
  }
}
override_resource {
  target = azurerm_storage_container.pipeline_payloads[0]
  values = {
    id = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/rg-kmlsat-dev-application/providers/Microsoft.Storage/storageAccounts/kmlsatdevappabc123/blobServices/default/containers/pipeline-payloads"
  }
}

variables {
  phase                      = "storage"
  context_path               = "../../../tests/fixtures/foundation/dev/context.json"
  bootstrap_path             = "../../../tests/fixtures/foundation/dev/bootstrap.json"
  writes_enabled             = true
  approved_storage_ip_ranges = ["203.0.113.10"]
  artifacts = [
    "../../../tests/fixtures/foundation/dev/namespace.json",
    "../../../tests/fixtures/foundation/dev/prerequisites.json",
    "../../../tests/fixtures/foundation/dev/custody.json",
    "../../../tests/fixtures/foundation/dev/key.json",
    "../../../tests/fixtures/foundation/dev/encryption.json",
  ]
}

run "cosmos-key" {
  command = plan
  variables { phase = "cosmos-key" }
  assert {
    condition = (
      length(azurerm_storage_account.main) == 1 &&
      length(azurerm_key_vault_key.storage_cmk) == 1 &&
      length(azurerm_key_vault_key.cosmos_cmk) == 1 &&
      length(azapi_resource.cosmos) == 0 &&
      timecmp(azurerm_key_vault_key.cosmos_cmk[0].expiration_date, timeadd(plantimestamp(), "4320h")) == 0 &&
      jsondecode(data.external.artifact.query.candidate).key_uri == azurerm_key_vault_key.cosmos_cmk[0].versionless_id
    )
    error_message = "Cosmos key preparation must preserve Blob resources and cannot create an account before its grant."
  }
}

run "cosmos" {
  command = plan
  variables {
    phase = "cosmos"
    artifacts = [
      "../../../tests/fixtures/foundation/dev/namespace.json",
      "../../../tests/fixtures/foundation/dev/prerequisites.json",
      "../../../tests/fixtures/foundation/dev/custody.json",
      "../../../tests/fixtures/foundation/dev/key.json",
      "../../../tests/fixtures/foundation/dev/encryption.json",
      "../../../tests/fixtures/foundation/dev/cosmos-key.json",
      "../../../tests/fixtures/foundation/dev/cosmos-encryption.json",
    ]
  }
  assert {
    condition = (
      length(azurerm_storage_account.main) == 1 &&
      azapi_resource.cosmos[0].body.properties.disableLocalAuth &&
      azapi_resource.cosmos[0].body.properties.disableKeyBasedMetadataWriteAccess &&
      azapi_resource.cosmos[0].body.properties.publicNetworkAccess == "Disabled" &&
      azapi_resource.cosmos[0].body.properties.networkAclBypass == "None" &&
      azapi_resource.cosmos[0].body.properties.backupPolicy.continuousModeProperties.tier == "Continuous7Days" &&
      azapi_resource.cosmos[0].body.properties.defaultIdentity == "UserAssignedIdentity=${azurerm_user_assigned_identity.cosmos_cmk[0].id}" &&
      azapi_resource.cosmos[0].body.properties.keyVaultKeyUri == azurerm_key_vault_key.cosmos_cmk[0].versionless_id
    )
    error_message = "Cosmos must preserve Blob and require closed networking, Entra, continuous recovery and its dedicated CMK/UAMI."
  }
  assert {
    condition = (
      jsondecode(data.external.artifact.query.candidate).cosmos.data_plane_available == false &&
      length(jsondecode(data.external.artifact.query.candidate).cosmos.containers) == 8
    )
    error_message = "Cosmos references must remain unavailable and contain exactly the existing eight containers."
  }
}

run "prerequisites" {
  command = plan
  variables {
    phase     = "prerequisites"
    artifacts = ["../../../tests/fixtures/foundation/dev/namespace.json"]
  }
  assert {
    condition     = length(azurerm_key_vault_key.storage_cmk) == 0 && length(azurerm_storage_account.main) == 0
    error_message = "Prerequisites cannot fabricate later key or storage resources."
  }
  assert {
    condition     = jsondecode(output.foundation_artifact).stage == "prerequisites" && jsondecode(output.foundation_artifact).payload.vault_id == data.external.inputs.result.vault_id
    error_message = "The validated prerequisites must echo the governance-owned vault."
  }
}

run "key" {
  command = plan
  variables {
    phase = "key"
    artifacts = [
      "../../../tests/fixtures/foundation/dev/namespace.json",
      "../../../tests/fixtures/foundation/dev/prerequisites.json",
      "../../../tests/fixtures/foundation/dev/custody.json",
    ]
  }
  assert {
    condition     = length(azurerm_key_vault_key.storage_cmk) == 1 && length(azurerm_storage_account.main) == 0
    error_message = "Key custody must precede key creation; storage still needs an encryption grant."
  }
  assert {
    condition     = jsondecode(output.foundation_artifact).stage == "key"
    error_message = "Key output must pass the shared validator."
  }
  assert {
    condition = (
      azurerm_key_vault_key.storage_cmk[0].key_vault_id == data.external.inputs.result.vault_id &&
      azurerm_key_vault_key.storage_cmk[0].rotation_policy[0].expire_after == "P180D" &&
      azurerm_key_vault_key.storage_cmk[0].rotation_policy[0].automatic[0].time_after_creation == "P90D" &&
      timecmp(azurerm_key_vault_key.storage_cmk[0].expiration_date, timeadd(plantimestamp(), "4320h")) == 0
    )
    error_message = "Initial and rotated expiry must be 180 days, rotation 90 days, under governance custody."
  }
  assert {
    condition     = lower(azurerm_user_assigned_identity.storage_cmk.principal_id) == local.payloads[1].encryption_principal_id && azurerm_user_assigned_identity.storage_cmk.principal_id != local.payloads[1].encryption_principal_id
    error_message = "Native binding must accept the same approved UUID despite different letter case."
  }
}

run "storage" {
  command = plan
  variables { phase = "storage" }
  assert {
    condition = (
      !azurerm_storage_account.main[0].shared_access_key_enabled &&
      !azurerm_storage_account.main[0].allow_nested_items_to_be_public &&
      azurerm_storage_account.main[0].default_to_oauth_authentication &&
      azurerm_storage_account.main[0].https_traffic_only_enabled &&
      azurerm_storage_account.main[0].min_tls_version == "TLS1_2" &&
      azurerm_storage_account.main[0].infrastructure_encryption_enabled &&
      azurerm_storage_account.main[0].network_rules[0].default_action == "Deny" &&
      azurerm_storage_account.main[0].network_rules[0].ip_rules == toset(["203.0.113.10"]) &&
      azurerm_storage_account.main[0].network_rules[0].bypass == toset(["None"])
    )
    error_message = "Storage requires Entra, strong transport/encryption and explicit deny-default egress."
  }

  assert {
    condition = (
      azurerm_storage_account.main[0].blob_properties[0].versioning_enabled &&
      azurerm_storage_account.main[0].blob_properties[0].delete_retention_policy[0].days == 30 &&
      azurerm_storage_account.main[0].blob_properties[0].container_delete_retention_policy[0].days == 30 &&
      length(azurerm_storage_account.main[0].blob_properties[0].cors_rule) == 0 &&
      alltrue([for container in [azurerm_storage_container.kml_input[0], azurerm_storage_container.kml_output[0], azurerm_storage_container.pipeline_payloads[0]] : container.container_access_type == "private"])
    )
    error_message = "Private Blob recovery/versioning and no browser origins are load-bearing defaults."
  }
  assert {
    condition = (
      azurerm_storage_account.main[0].customer_managed_key[0].key_vault_key_id == azurerm_key_vault_key.storage_cmk[0].versionless_id &&
      azurerm_storage_account.main[0].customer_managed_key[0].user_assigned_identity_id == azurerm_user_assigned_identity.storage_cmk.id &&
      azurerm_log_analytics_workspace.main.retention_in_days == 30 &&
      azurerm_log_analytics_workspace.main.local_authentication_disabled &&
      !azurerm_log_analytics_workspace.main.allow_resource_only_permissions &&
      toset([for log in azurerm_monitor_diagnostic_setting.storage_blob[0].enabled_log : log.category]) == toset(["StorageRead", "StorageWrite", "StorageDelete"]) &&
      one(azurerm_monitor_diagnostic_setting.vault.enabled_log).category == "AuditEvent"
    )
    error_message = "CMK and dedicated Entra-only auditing must be preserved."
  }
  assert {
    condition     = jsondecode(data.external.artifact.query.candidate).status == "not-activated" && !jsondecode(data.external.artifact.query.candidate).storage.data_plane_available && jsondecode(data.external.artifact.query.candidate).contract_scope == "persistent-data-core"
    error_message = "The manifest candidate must not claim readiness; the native runner executes its deferred semantic validation."
  }
}

run "closed_by_default" {
  command = plan
  variables {
    writes_enabled = false
  }
  expect_failures = [data.external.inputs]
}

run "requires_approved_egress" {
  command = plan
  variables {
    phase                      = "storage"
    approved_storage_ip_ranges = []
  }
  expect_failures = [azurerm_storage_account.main]
}

run "rejects_global_egress" {
  command = plan
  variables {
    phase                      = "storage"
    approved_storage_ip_ranges = ["0.0.0.0/0"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "accepts_public_storage_egress_boundaries" {
  command = plan
  variables {
    phase                      = "storage"
    approved_storage_ip_ranges = ["203.0.113.10", "11.0.0.0/8", "203.0.113.8/30", "172.15.0.1", "172.32.0.1"]
  }
  assert {
    condition     = azurerm_storage_account.main[0].network_rules[0].ip_rules == toset(var.approved_storage_ip_ranges)
    error_message = "Public standalone IPv4 and /8-/30 CIDRs must reach the storage firewall unchanged."
  }
}

# Validate before storage exists, so provider rejection cannot mask the missing variable guard.
run "rejects_private_10_cidr" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["10.0.0.0/24"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_private_10_address" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["10.255.255.255"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_private_172_cidr" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["172.16.0.0/12"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_private_172_address" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["172.31.255.255"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_private_192_cidr" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["192.168.0.0/16"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_private_192_address" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["192.168.1.1"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_cidr_31" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["203.0.113.10/31"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_cidr_32" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["203.0.113.10/32"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_cidr_below_minimum" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["12.0.0.0/7"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_malformed_ipv4" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["203.0.113.256"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

run "rejects_ipv6" {
  command = plan
  variables {
    phase                      = "prerequisites"
    artifacts                  = ["../../../tests/fixtures/foundation/dev/namespace.json"]
    approved_storage_ip_ranges = ["2001:db8::/32"]
  }
  expect_failures = [var.approved_storage_ip_ranges]
}

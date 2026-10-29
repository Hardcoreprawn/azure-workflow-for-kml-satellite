provider "azapi" {
  subscription_id            = local.context.subscription_id
  tenant_id                  = local.context.tenant_id
  client_id                  = local.context.foundation.client_id
  use_oidc                   = true
  use_cli                    = false
  use_msi                    = false
  skip_provider_registration = true
  disable_default_output     = true
  enable_preflight           = false
}

resource "azurerm_user_assigned_identity" "cosmos_cmk" {
  count               = local.cosmos_key_enabled ? 1 : 0
  name                = "id-${local.name_suffix}-cosmos-encryption"
  resource_group_name = data.external.inputs.result.namespace_name
  location            = local.context.location
  tags                = local.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_key_vault_key" "cosmos_cmk" {
  count           = local.cosmos_key_enabled ? 1 : 0
  name            = "cosmos-cmk"
  key_vault_id    = data.external.inputs.result.vault_id
  key_type        = "RSA"
  key_size        = 2048
  key_opts        = ["unwrapKey", "wrapKey"]
  expiration_date = timeadd(plantimestamp(), "4320h")
  tags            = local.tags
  rotation_policy {
    expire_after         = "P180D"
    notify_before_expiry = "P30D"
    automatic {
      time_after_creation = "P90D"
    }
  }
  lifecycle {
    prevent_destroy = true
    ignore_changes  = [expiration_date]
    postcondition {
      condition     = try(timecmp(self.expiration_date, plantimestamp()) > 0, false)
      error_message = "Cosmos key requires an effective future expiry; policy alone does not prove rotation."
    }
  }
}

# AzureRM 4.22 account refresh reads account credentials. AzAPI ARM CRUD does not.
resource "azapi_resource" "cosmos" {
  count     = local.cosmos_ready ? 1 : 0
  type      = "Microsoft.DocumentDB/databaseAccounts@2024-11-15"
  parent_id = data.external.inputs.result.namespace_id
  name      = "cosmos-${local.name_suffix}"
  location  = local.context.location
  tags      = local.tags
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.cosmos_cmk[0].id]
  }
  response_export_values    = ["properties.documentEndpoint"]
  schema_validation_enabled = true
  body = {
    kind = "GlobalDocumentDB"
    properties = {
      databaseAccountOfferType           = "Standard"
      capabilities                       = [{ name = "EnableServerless" }]
      consistencyPolicy                  = { defaultConsistencyLevel = "Session" }
      locations                          = [{ locationName = local.context.location, failoverPriority = 0, isZoneRedundant = false }]
      enableAutomaticFailover            = false
      enableMultipleWriteLocations       = false
      disableLocalAuth                   = true
      disableKeyBasedMetadataWriteAccess = true
      publicNetworkAccess                = "Disabled"
      networkAclBypass                   = "None"
      networkAclBypassResourceIds        = []
      ipRules                            = []
      virtualNetworkRules                = []
      minimalTlsVersion                  = "Tls12"
      backupPolicy                       = { type = "Continuous", continuousModeProperties = { tier = "Continuous7Days" } }
      keyVaultKeyUri                     = azurerm_key_vault_key.cosmos_cmk[0].versionless_id
      defaultIdentity                    = "UserAssignedIdentity=${azurerm_user_assigned_identity.cosmos_cmk[0].id}"
    }
  }
  lifecycle {
    prevent_destroy = true
    precondition {
      condition = (
        lower(local.payloads[5].key_id) == lower(azurerm_key_vault_key.cosmos_cmk[0].resource_versionless_id) &&
        local.payloads[5].key_uri == azurerm_key_vault_key.cosmos_cmk[0].versionless_id &&
        lower(local.payloads[5].encryption_identity_id) == lower(azurerm_user_assigned_identity.cosmos_cmk[0].id) &&
        lower(local.payloads[5].encryption_client_id) == lower(azurerm_user_assigned_identity.cosmos_cmk[0].client_id) &&
        lower(local.payloads[5].encryption_principal_id) == lower(azurerm_user_assigned_identity.cosmos_cmk[0].principal_id)
      )
      error_message = "Cosmos governance grant must bind the actual refreshed dedicated key and encryption identity."
    }
  }
}

resource "azurerm_cosmosdb_sql_database" "main" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "treesight"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "cosmos" {
  count                      = local.cosmos_ready ? 1 : 0
  name                       = "application-cosmos-control-plane"
  target_resource_id         = azapi_resource.cosmos[0].id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  enabled_log {
    category = "ControlPlaneRequests"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_cosmosdb_sql_container" "runs" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "runs"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/user_id"]
  default_ttl         = -1
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/submitted_at/?" }
    included_path { path = "/status/?" }
    excluded_path { path = "/*" }
    composite_index {
      index {
        path  = "/submitted_at"
        order = "descending"
      }
      index {
        path  = "/status"
        order = "ascending"
      }
    }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_cosmosdb_sql_container" "subscriptions" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "subscriptions"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/user_id"]
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/status/?" }
    included_path { path = "/stripe_customer_id/?" }
    excluded_path { path = "/*" }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_cosmosdb_sql_container" "users" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "users"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/user_id"]
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/email/?" }
    excluded_path { path = "/*" }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_cosmosdb_sql_container" "monitors" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "monitors"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/user_id"]
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/enabled/?" }
    included_path { path = "/next_check_at/?" }
    included_path { path = "/created_at/?" }
    excluded_path { path = "/*" }
    composite_index {
      index {
        path  = "/enabled"
        order = "ascending"
      }
      index {
        path  = "/next_check_at"
        order = "ascending"
      }
    }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_cosmosdb_sql_container" "catalogue" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "catalogue"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/user_id"]
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/submitted_at/?" }
    included_path { path = "/aoi_name/?" }
    included_path { path = "/status/?" }
    included_path { path = "/run_id/?" }
    included_path { path = "/provider/?" }
    excluded_path { path = "/*" }
    composite_index {
      index {
        path  = "/submitted_at"
        order = "descending"
      }
      index {
        path  = "/status"
        order = "ascending"
      }
    }
    composite_index {
      index {
        path  = "/aoi_name"
        order = "ascending"
      }
      index {
        path  = "/submitted_at"
        order = "descending"
      }
    }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_cosmosdb_sql_container" "orgs" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "orgs"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/org_id"]
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/doc_type/?" }
    included_path { path = "/members/[]/user_id/?" }
    included_path { path = "/created_at/?" }
    excluded_path { path = "/*" }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_cosmosdb_sql_container" "feature_flags" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "feature_flags"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/feature_name"]
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/status/?" }
    included_path { path = "/kill_switch/?" }
    excluded_path { path = "/*" }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_cosmosdb_sql_container" "feature_flag_overrides" {
  count               = local.cosmos_ready ? 1 : 0
  name                = "feature_flag_overrides"
  resource_group_name = data.external.inputs.result.namespace_name
  account_name        = azapi_resource.cosmos[0].name
  database_name       = azurerm_cosmosdb_sql_database.main[0].name
  partition_key_paths = ["/user_id"]
  indexing_policy {
    indexing_mode = "consistent"
    included_path { path = "/user_id/?" }
    excluded_path { path = "/*" }
  }
  lifecycle { prevent_destroy = true }
}

locals {
  prerequisites_payload = {
    vault_id                = data.external.inputs.result.vault_id
    encryption_identity_id  = azurerm_user_assigned_identity.storage_cmk.id
    encryption_client_id    = azurerm_user_assigned_identity.storage_cmk.client_id
    encryption_principal_id = azurerm_user_assigned_identity.storage_cmk.principal_id
    audit_workspace_id      = azurerm_log_analytics_workspace.main.id
    vault_diagnostic_id     = "${azurerm_monitor_diagnostic_setting.vault.target_resource_id}/providers/Microsoft.Insights/diagnosticSettings/${azurerm_monitor_diagnostic_setting.vault.name}"
  }
  key_payload = local.key_enabled ? {
    key_id  = azurerm_key_vault_key.storage_cmk[0].resource_versionless_id
    key_uri = azurerm_key_vault_key.storage_cmk[0].versionless_id
  } : null
  cosmos_key_payload = local.cosmos_key_enabled ? {
    key_id                  = azurerm_key_vault_key.cosmos_cmk[0].resource_versionless_id
    key_uri                 = azurerm_key_vault_key.cosmos_cmk[0].versionless_id
    encryption_identity_id  = azurerm_user_assigned_identity.cosmos_cmk[0].id
    encryption_client_id    = azurerm_user_assigned_identity.cosmos_cmk[0].client_id
    encryption_principal_id = azurerm_user_assigned_identity.cosmos_cmk[0].principal_id
  } : null
  cosmos_manifest = local.cosmos_ready ? {
    id                   = azapi_resource.cosmos[0].id
    name                 = azapi_resource.cosmos[0].name
    endpoint             = azapi_resource.cosmos[0].output.properties.documentEndpoint
    data_plane_available = false
    database = {
      id   = azurerm_cosmosdb_sql_database.main[0].id
      name = azurerm_cosmosdb_sql_database.main[0].name
    }
    containers = {
      for container in [
        azurerm_cosmosdb_sql_container.runs[0],
        azurerm_cosmosdb_sql_container.subscriptions[0],
        azurerm_cosmosdb_sql_container.users[0],
        azurerm_cosmosdb_sql_container.monitors[0],
        azurerm_cosmosdb_sql_container.catalogue[0],
        azurerm_cosmosdb_sql_container.orgs[0],
        azurerm_cosmosdb_sql_container.feature_flags[0],
        azurerm_cosmosdb_sql_container.feature_flag_overrides[0],
      ] : container.name => { id = container.id, name = container.name }
    }
    encryption = {
      key_id       = local.cosmos_key_payload.key_id
      key_uri      = local.cosmos_key_payload.key_uri
      identity_id  = local.cosmos_key_payload.encryption_identity_id
      client_id    = local.cosmos_key_payload.encryption_client_id
      principal_id = local.cosmos_key_payload.encryption_principal_id
      grant_sha256 = filesha256(var.artifacts[6])
    }
    diagnostic_id = "${azurerm_monitor_diagnostic_setting.cosmos[0].target_resource_id}/providers/Microsoft.Insights/diagnosticSettings/${azurerm_monitor_diagnostic_setting.cosmos[0].name}"
  } : null
  manifest = local.storage_ready ? {
    schema_version          = 2
    contract_scope          = "persistent-data-core"
    status                  = "not-activated"
    environment             = local.context.environment
    tenant_id               = local.context.tenant_id
    subscription_id         = local.context.subscription_id
    producer                = "foundation"
    producer_revision       = local.context.foundation_revision
    policy_revision         = local.context.policy_revision
    bootstrap_sha256        = filesha256(var.bootstrap_path)
    encryption_grant_sha256 = filesha256(var.artifacts[4])
    namespace = {
      id       = data.external.inputs.result.namespace_id
      name     = data.external.inputs.result.namespace_name
      location = local.context.location
    }
    storage = {
      id                   = azurerm_storage_account.main[0].id
      name                 = azurerm_storage_account.main[0].name
      blob_endpoint        = azurerm_storage_account.main[0].primary_blob_endpoint
      data_plane_available = false
      containers = {
        kml_input = {
          id   = azurerm_storage_container.kml_input[0].id
          name = azurerm_storage_container.kml_input[0].name
        }
        kml_output = {
          id   = azurerm_storage_container.kml_output[0].id
          name = azurerm_storage_container.kml_output[0].name
        }
        pipeline_payloads = {
          id   = azurerm_storage_container.pipeline_payloads[0].id
          name = azurerm_storage_container.pipeline_payloads[0].name
        }
      }
    }
    encryption = {
      vault_id     = data.external.inputs.result.vault_id
      vault_uri    = data.external.inputs.result.vault_uri
      key_id       = local.key_payload.key_id
      key_uri      = local.key_payload.key_uri
      identity_id  = azurerm_user_assigned_identity.storage_cmk.id
      client_id    = azurerm_user_assigned_identity.storage_cmk.client_id
      principal_id = azurerm_user_assigned_identity.storage_cmk.principal_id
    }
    audit = {
      workspace_id        = azurerm_log_analytics_workspace.main.id
      vault_diagnostic_id = local.prerequisites_payload.vault_diagnostic_id
      blob_diagnostic_id  = "${azurerm_monitor_diagnostic_setting.storage_blob[0].target_resource_id}/providers/Microsoft.Insights/diagnosticSettings/${azurerm_monitor_diagnostic_setting.storage_blob[0].name}"
    }
    approved_browser_origins = []
    cosmos                   = local.cosmos_manifest
  } : null
}

data "external" "artifact" {
  program     = ["python3", "-m", "scripts.validate_foundation_contract", "external-output"]
  working_dir = "${path.module}/../../.."
  query = {
    context      = file(var.context_path)
    bootstrap    = file(var.bootstrap_path)
    artifacts    = jsonencode([for path in var.artifacts : file(path)])
    phase        = var.phase
    candidate    = var.phase == "prerequisites" ? jsonencode(local.prerequisites_payload) : (var.phase == "key" ? jsonencode(local.key_payload) : (var.phase == "cosmos-key" ? jsonencode(local.cosmos_key_payload) : jsonencode(local.manifest)))
    storage_name = contains(["storage", "cosmos"], var.phase) ? azurerm_storage_account.main[0].name : ""
  }
}

output "foundation_artifact" {
  description = "Canonical validated raw JSON. Prerequisites/key/cosmos-key are partial declarations; storage/cosmos are persistent-data-core/not-activated, never data-plane readiness."
  value       = data.external.artifact.result.contract
}

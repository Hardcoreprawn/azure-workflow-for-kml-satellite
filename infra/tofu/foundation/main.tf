data "external" "inputs" {
  program     = ["python3", "-m", "scripts.validate_foundation_contract", "external-gate"]
  working_dir = "${path.module}/../../.."
  query = {
    context        = file(var.context_path)
    bootstrap      = file(var.bootstrap_path)
    artifacts      = jsonencode([for path in var.artifacts : file(path)])
    phase          = var.phase
    writes_enabled = tostring(var.writes_enabled)
  }
  lifecycle {
    precondition {
      condition     = var.writes_enabled
      error_message = "Foundation writes are closed by default."
    }
  }
}

locals {
  context            = jsondecode(data.external.inputs.result.context)
  payloads           = jsondecode(data.external.inputs.result.payloads)
  key_enabled        = contains(["key", "storage", "cosmos-key", "cosmos"], var.phase)
  storage_ready      = contains(["storage", "cosmos-key", "cosmos"], var.phase)
  cosmos_key_enabled = contains(["cosmos-key", "cosmos"], var.phase)
  cosmos_ready       = var.phase == "cosmos"
  name_suffix        = "${local.context.project_code}-${local.context.environment}-application"
  tags = {
    project     = local.context.project_code
    environment = local.context.environment
    managed-by  = "opentofu"
    component   = "persistent-data-core"
  }
}

provider "azurerm" {
  features {
    storage {
      data_plane_available = false
    }
  }
  subscription_id                 = local.context.subscription_id
  tenant_id                       = local.context.tenant_id
  client_id                       = local.context.foundation.client_id
  use_oidc                        = true
  use_cli                         = false
  use_msi                         = false
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

resource "random_string" "storage_suffix" {
  length     = 6
  upper      = false
  special    = false
  depends_on = [data.external.inputs]
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_user_assigned_identity" "storage_cmk" {
  name                = "id-${local.name_suffix}-encryption"
  resource_group_name = data.external.inputs.result.namespace_name
  location            = local.context.location
  tags                = local.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_log_analytics_workspace" "main" {
  name                            = "law-${local.name_suffix}"
  resource_group_name             = data.external.inputs.result.namespace_name
  location                        = local.context.location
  sku                             = "PerGB2018"
  retention_in_days               = 30
  local_authentication_disabled   = true
  allow_resource_only_permissions = false
  tags                            = local.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "vault" {
  name                       = "application-key-audit"
  target_resource_id         = data.external.inputs.result.vault_id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  enabled_log {
    category = "AuditEvent"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_key_vault_key" "storage_cmk" {
  count           = local.key_enabled ? 1 : 0
  name            = "application-cmk"
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
    # Azure rotation owns subsequent expiry. Never reset it to a moving initial date.
    ignore_changes = [expiration_date]
    precondition {
      condition = (
        lower(local.payloads[1].encryption_identity_id) == lower(azurerm_user_assigned_identity.storage_cmk.id) &&
        lower(local.payloads[1].encryption_client_id) == lower(azurerm_user_assigned_identity.storage_cmk.client_id) &&
        lower(local.payloads[1].encryption_principal_id) == lower(azurerm_user_assigned_identity.storage_cmk.principal_id) &&
        lower(local.payloads[1].audit_workspace_id) == lower(azurerm_log_analytics_workspace.main.id)
      )
      error_message = "Custody must bind this exact refreshed foundation prerequisite set."
    }
    postcondition {
      condition     = try(timecmp(self.expiration_date, plantimestamp()) > 0, false)
      error_message = "The refreshed effective application key must have a future expiry; rotation is not proven by policy."
    }
  }
}

resource "azurerm_storage_account" "main" {
  count                             = local.storage_ready ? 1 : 0
  name                              = "${local.context.project_code}${local.context.environment}app${random_string.storage_suffix.result}"
  resource_group_name               = data.external.inputs.result.namespace_name
  location                          = local.context.location
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  account_kind                      = "StorageV2"
  https_traffic_only_enabled        = true
  min_tls_version                   = "TLS1_2"
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  public_network_access_enabled     = true
  infrastructure_encryption_enabled = true
  tags                              = local.tags
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.storage_cmk.id]
  }
  customer_managed_key {
    key_vault_key_id          = azurerm_key_vault_key.storage_cmk[0].versionless_id
    user_assigned_identity_id = azurerm_user_assigned_identity.storage_cmk.id
  }
  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
    ip_rules       = var.approved_storage_ip_ranges
  }
  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = length(var.approved_storage_ip_ranges) > 0
      error_message = "Storage creation requires explicit owner-approved egress; no hosted-runner assumption."
    }
    precondition {
      condition = (
        lower(local.payloads[3].key_id) == lower(azurerm_key_vault_key.storage_cmk[0].resource_versionless_id) &&
        local.payloads[3].key_uri == azurerm_key_vault_key.storage_cmk[0].versionless_id
      )
      error_message = "The governance encryption grant must bind this exact refreshed application key."
    }
  }
}

resource "azurerm_storage_container" "kml_input" {
  count                 = local.storage_ready ? 1 : 0
  name                  = "kml-input"
  storage_account_id    = azurerm_storage_account.main[0].id
  container_access_type = "private"
  lifecycle {
    prevent_destroy = true
  }
}
resource "azurerm_storage_container" "kml_output" {
  count                 = local.storage_ready ? 1 : 0
  name                  = "kml-output"
  storage_account_id    = azurerm_storage_account.main[0].id
  container_access_type = "private"
  lifecycle {
    prevent_destroy = true
  }
}
resource "azurerm_storage_container" "pipeline_payloads" {
  count                 = local.storage_ready ? 1 : 0
  name                  = "pipeline-payloads"
  storage_account_id    = azurerm_storage_account.main[0].id
  container_access_type = "private"
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "storage_blob" {
  count                      = local.storage_ready ? 1 : 0
  name                       = "application-blob-audit"
  target_resource_id         = "${azurerm_storage_account.main[0].id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  enabled_log {
    category = "StorageRead"
  }
  enabled_log {
    category = "StorageWrite"
  }
  enabled_log {
    category = "StorageDelete"
  }
  lifecycle {
    prevent_destroy = true
  }
}

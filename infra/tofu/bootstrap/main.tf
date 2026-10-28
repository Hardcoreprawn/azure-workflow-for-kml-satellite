provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

locals {
  key_enabled  = contains(["key", "state"], var.bootstrap_phase)
  state_layers = var.bootstrap_phase == "state" ? toset(["foundation", "workload"]) : toset([])
  identities   = toset(["foundation", "workload", "release"])
  name_suffix  = "${var.project_code}-${var.environment}"
  tags = {
    project     = "kml-satellite"
    environment = var.environment
    managed-by  = "opentofu"
    owner       = "platform"
    component   = "bootstrap"
  }
}

resource "azurerm_resource_group" "bootstrap" {
  name     = "rg-${local.name_suffix}-bootstrap"
  location = var.location
  tags     = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_string" "storage_suffix" {
  length  = 6
  upper   = false
  special = false
}

data "azurerm_client_config" "operator" {}

resource "azurerm_log_analytics_workspace" "audit" {
  name                            = "law-${local.name_suffix}-bootstrap"
  resource_group_name             = azurerm_resource_group.bootstrap.name
  location                        = azurerm_resource_group.bootstrap.location
  sku                             = "PerGB2018"
  retention_in_days               = 30
  local_authentication_disabled   = true
  allow_resource_only_permissions = false
  tags                            = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_key_vault" "state" {
  name                       = "k${var.project_code}${var.environment}v${random_string.storage_suffix.result}"
  resource_group_name        = azurerm_resource_group.bootstrap.name
  location                   = azurerm_resource_group.bootstrap.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  soft_delete_retention_days = 90
  purge_protection_enabled   = true
  tags                       = local.tags

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
    ip_rules       = var.bootstrap_allowed_ip_ranges
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "vault" {
  name                       = "bootstrap-key-audit"
  target_resource_id         = azurerm_key_vault.state.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.audit.id

  enabled_log {
    category = "AuditEvent"
  }
}

resource "azurerm_user_assigned_identity" "storage_encryption" {
  name                = "id-${local.name_suffix}-state-encryption"
  resource_group_name = azurerm_resource_group.bootstrap.name
  location            = azurerm_resource_group.bootstrap.location
  tags                = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_role_assignment" "key_custodian" {
  scope                = azurerm_key_vault.state.id
  role_definition_name = "Key Vault Crypto Officer"
  principal_id         = var.bootstrap_operator_object_id

  lifecycle {
    precondition {
      condition     = data.azurerm_client_config.operator.object_id == var.bootstrap_operator_object_id
      error_message = "Authenticate as the explicitly approved bootstrap key custodian."
    }
    precondition {
      condition = !contains(
        concat(
          [for identity in azurerm_user_assigned_identity.deployment : identity.principal_id],
          [azurerm_user_assigned_identity.storage_encryption.principal_id]
        ),
        var.bootstrap_operator_object_id
      )
      error_message = "Bootstrap key custody must remain separate from deployment and storage-encryption identities."
    }
  }
}

resource "azurerm_key_vault_key" "state" {
  count           = local.key_enabled ? 1 : 0
  name            = "bootstrap-state"
  key_vault_id    = azurerm_key_vault.state.id
  key_type        = "RSA"
  key_size        = 2048
  key_opts        = ["unwrapKey", "wrapKey"]
  expiration_date = var.state_key_expiration_date
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
  }

  depends_on = [azurerm_role_assignment.key_custodian]
}

resource "azurerm_role_assignment" "storage_encryption" {
  count                            = local.key_enabled ? 1 : 0
  scope                            = azurerm_key_vault_key.state[0].resource_versionless_id
  role_definition_name             = "Key Vault Crypto Service Encryption User"
  principal_id                     = azurerm_user_assigned_identity.storage_encryption.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_storage_account" "state" {
  count                             = var.bootstrap_phase == "state" ? 1 : 0
  name                              = "${var.project_code}${var.environment}tf${random_string.storage_suffix.result}"
  resource_group_name               = azurerm_resource_group.bootstrap.name
  location                          = azurerm_resource_group.bootstrap.location
  account_tier                      = "Standard"
  account_replication_type          = "LRS"
  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  infrastructure_encryption_enabled = true
  tags                              = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.storage_encryption.id]
  }

  customer_managed_key {
    key_vault_key_id          = azurerm_key_vault_key.state[0].versionless_id
    user_assigned_identity_id = azurerm_user_assigned_identity.storage_encryption.id
  }

  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
    ip_rules       = var.bootstrap_allowed_ip_ranges
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
  }

  depends_on = [azurerm_role_assignment.storage_encryption]
}

resource "azurerm_storage_container" "state" {
  for_each              = local.state_layers
  name                  = each.key
  storage_account_id    = azurerm_storage_account.state[0].id
  container_access_type = "private"

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_monitor_diagnostic_setting" "state" {
  count                      = var.bootstrap_phase == "state" ? 1 : 0
  name                       = "bootstrap-state-audit"
  target_resource_id         = "${azurerm_storage_account.state[0].id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.audit.id

  dynamic "enabled_log" {
    for_each = toset(["StorageRead", "StorageWrite", "StorageDelete"])
    content {
      category = enabled_log.value
    }
  }
}

resource "azurerm_user_assigned_identity" "deployment" {
  for_each            = local.identities
  name                = "id-${local.name_suffix}-${each.key}"
  resource_group_name = azurerm_resource_group.bootstrap.name
  location            = azurerm_resource_group.bootstrap.location
  tags                = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_role_assignment" "state" {
  for_each                         = local.state_layers
  scope                            = azurerm_storage_container.state[each.key].id
  role_definition_name             = "Storage Blob Data Contributor"
  principal_id                     = azurerm_user_assigned_identity.deployment[each.key].principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_federated_identity_credential" "github" {
  for_each            = var.enable_github_oidc ? local.identities : toset([])
  name                = "github-${var.environment}-${each.key}"
  resource_group_name = azurerm_resource_group.bootstrap.name
  parent_id           = azurerm_user_assigned_identity.deployment[each.key].id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:Hardcoreprawn/azure-workflow-for-kml-satellite:environment:${var.environment}-${each.key}"
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

locals {
  state_layers = toset(["foundation", "workload"])
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

resource "azurerm_storage_account" "state" {
  name                            = "${var.project_code}${var.environment}tf${random_string.storage_suffix.result}"
  resource_group_name             = azurerm_resource_group.bootstrap.name
  location                        = azurerm_resource_group.bootstrap.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  tags                            = local.tags

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
}

resource "azurerm_storage_container" "state" {
  for_each              = local.state_layers
  name                  = each.key
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"

  lifecycle {
    prevent_destroy = true
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

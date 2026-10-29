terraform {
  required_version = "= 1.13.2"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.22.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.6.3"
    }
    external = {
      source  = "hashicorp/external"
      version = "2.3.5"
    }
  }
  backend "azurerm" {
    resource_group_name  = local.selected_backend.resource_group_name
    storage_account_name = local.selected_backend.storage_account_name
    container_name       = local.selected_backend.container_name
    key                  = local.selected_backend.key
    tenant_id            = local.selected_backend.tenant_id
    subscription_id      = local.selected_backend.subscription_id
    client_id            = local.selected_backend.client_id
    use_azuread_auth     = true
    use_oidc             = true
    use_cli              = false
  }
}

locals {
  # OpenTofu early evaluation binds backend selection to the same independently
  # supplied context that the mandatory resource-write validator checks.
  selected_backend = jsondecode(file(var.context_path)).backend
}

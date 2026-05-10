provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

provider "azapi" {
  subscription_id = var.subscription_id
}

# Authenticates to the Entra External ID (CIAM) tenant to manage the app
# registration's SPA redirect URIs. Requires a service principal in the CIAM
# tenant with Application.ReadWrite.OwnedBy, federated via OIDC for this repo.
provider "azuread" {
  tenant_id = var.ciam_tenant_id != "" ? var.ciam_tenant_id : null
  client_id = var.ciam_deploy_client_id != "" ? var.ciam_deploy_client_id : null
  use_oidc  = true
}

data "azurerm_client_config" "current" {}

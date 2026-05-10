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
#
# When ciam_deploy_client_id is empty the azuread_application_redirect_uris
# resource is count = 0, so this provider is never called. Setting use_oidc
# conditionally prevents an OIDC token exchange attempt against the CIAM tenant
# when the deployment service principal is not configured (e.g. cost-estimate CI).
provider "azuread" {
  tenant_id = var.ciam_deploy_client_id != "" ? var.ciam_tenant_id : null
  client_id = var.ciam_deploy_client_id != "" ? var.ciam_deploy_client_id : null
  use_oidc  = var.ciam_deploy_client_id != ""
}

data "azurerm_client_config" "current" {}

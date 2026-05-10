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
# Both ciam_client_id AND ciam_deploy_client_id must be set for any azuread
# resources to be created (count = 0 otherwise). Gate the provider config on
# the same all-or-nothing condition so no OIDC exchange is attempted when
# either value is absent (e.g. cost-estimate CI, partial configuration).
locals {
  ciam_redirect_enabled = var.ciam_client_id != "" && var.ciam_deploy_client_id != ""
}

provider "azuread" {
  tenant_id = local.ciam_redirect_enabled ? var.ciam_tenant_id : null
  client_id = local.ciam_redirect_enabled ? var.ciam_deploy_client_id : null
  use_oidc  = local.ciam_redirect_enabled
}

data "azurerm_client_config" "current" {}

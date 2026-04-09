provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# Entra External ID (CIAM) tenant — manages the app registration used by
# SWA built-in auth.  Requires authentication against the CIAM tenant,
# either via Azure CLI (`az login --tenant <ciam_tenant_id>`) or a
# service principal with Application.ReadWrite.OwnedBy in that tenant.
provider "azuread" {
  tenant_id = var.ciam_tenant_id != "" ? var.ciam_tenant_id : null
}

provider "azapi" {
  subscription_id = var.subscription_id
}

data "azurerm_client_config" "current" {}

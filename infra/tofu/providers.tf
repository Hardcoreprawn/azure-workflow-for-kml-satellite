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
# ciam_client_id is validated as non-empty in variables.tf, so the gating
# condition reduces to: did the operator wire up the CIAM-tenant deploy SP?
# When ciam_deploy_client_id is empty (e.g. cost-estimate CI, bootstrap), the
# azuread provider stays unconfigured and no OIDC exchange is attempted.
locals {
  # nonsensitive() is safe here: the result is a boolean derived from a
  # zero-length check, which leaks no secret material. Required so the
  # boolean can be used as a `for_each` / `count` driver downstream
  # (Tofu refuses to use values derived from sensitive vars in those
  # contexts otherwise).
  ciam_redirect_enabled = nonsensitive(var.ciam_deploy_client_id != "")
}

provider "azuread" {
  tenant_id = local.ciam_redirect_enabled ? var.ciam_tenant_id : null
  client_id = local.ciam_redirect_enabled ? var.ciam_deploy_client_id : null
  use_oidc  = local.ciam_redirect_enabled
}

data "azurerm_client_config" "current" {}

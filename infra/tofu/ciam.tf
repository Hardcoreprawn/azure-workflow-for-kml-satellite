# --- Entra External ID (CIAM) app registration ---
#
# Manages the app registration used by SWA built-in auth (OIDC).
# Redirect URIs are derived from the SWA hostname so they stay in sync
# when the Static Web App is recreated.
#
# First-time import (existing app):
#   tofu import 'azuread_application.ciam[0]' \
#     /applications/7ce73a2a-b80a-4b6f-afb7-eccf74bfaf47
#
# Auth requirement:
#   The azuread provider must be authenticated against the CIAM tenant.
#   See providers.tf for details.

locals {
  ciam_enabled = var.ciam_tenant_id != "" && var.ciam_tenant_name != ""

  # SWA built-in auth callback path — fixed by the platform.
  auth_callback_path = "/.auth/login/aad/callback"

  # Redirect URIs: localhost (dev) + SWA default hostname + custom domain.
  ciam_redirect_uris = local.ciam_enabled ? compact([
    "http://localhost:4280${local.auth_callback_path}",
    "https://${azurerm_static_web_app.main.default_host_name}${local.auth_callback_path}",
    var.custom_domain != "" ? "https://${var.custom_domain}${local.auth_callback_path}" : "",
  ]) : []
}

resource "azuread_application" "ciam" {
  count            = local.ciam_enabled ? 1 : 0
  display_name     = "Canopex"
  sign_in_audience = "AzureADandPersonalMicrosoftAccount"

  api {
    requested_access_token_version = 2
  }

  web {
    redirect_uris = local.ciam_redirect_uris

    implicit_grant {
      id_token_issuance_enabled     = true
      access_token_issuance_enabled = false
    }
  }

  # Microsoft Graph delegated permissions: User.Read, openid, profile
  required_resource_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000" # Microsoft Graph

    resource_access {
      id   = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"
      type = "Scope" # User.Read
    }
    resource_access {
      id   = "37f7f235-527c-4136-accd-4a02d197296e"
      type = "Scope" # openid
    }
    resource_access {
      id   = "14dad69e-099b-42c9-810b-d002981feec1"
      type = "Scope" # profile
    }
  }

}

environment                       = "prd"
location                          = "uksouth"
static_web_app_location           = "westeurope"
location_code                     = "uks"
project_code                      = "kmlsat"
log_retention_days                = 31
log_daily_cap_gb                  = 0.5
enable_event_grid_subscription    = true
enable_key_vault_purge_protection = true
container_image                   = "mcr.microsoft.com/azure-functions/python:4-python3.12"
default_tags = {
  cost-center = "prd"
}
budget_amount         = 50
budget_contact_emails = ["alerts@jablab.dev"]
custom_domain         = "canopex.hrdcrprwn.com"
enable_azure_ai       = false
enable_stripe         = true
enable_cosmos_db      = true

# Scale orchestrator to zero — no idle container cost.
# HTTP cold starts are acceptable given the planned Flex Consumption migration (#846).
orch_min_instances    = 0
function_min_instances = 0

# --- CIAM (Entra External ID) ---
# Public values: visible in the deployed page HTML (canopex-ciam-config script).
# Tofu surfaces them as plain Function App app settings and a `ciam_page_config`
# output the SWA workflow injects into the page HTML at deploy time.
ciam_tenant_subdomain = "canopex"
ciam_tenant_id        = "98a402ed-45fb-4cf8-bbfe-2b4c19bc36c7"
ciam_client_id        = "1b51e2e8-15af-448b-8886-1345aeda73ba"
# CIAM External ID issues access tokens with `aud=<clientId>` when a SPA calls
# its own backend (no separate API app reg). Backend validates against this aud.
ciam_api_audience     = "1b51e2e8-15af-448b-8886-1345aeda73ba"

# Object IDs for Tofu state ownership of CIAM resources (issue #781/#806/#804).
# These are not secrets; they are GUIDs visible in the Azure portal.
#
# ciam_app_object_id: Object ID of the Canopex SPA app registration.
#   Find with: az ad app show --id 1b51e2e8-15af-448b-8886-1345aeda73ba \
#     --query id -o tsv --tenant 98a402ed-45fb-4cf8-bbfe-2b4c19bc36c7 \
#     --allow-no-subscriptions
#   Once set, `tofu plan` will show the import; `tofu apply` adopts it.
ciam_app_object_id = ""

# ciam_deploy_app_object_id: Object ID of the "Canopex Tofu Deploy" APP REGISTRATION.
#   Find with: az ad app show --id <TF_VAR_CIAM_DEPLOY_CLIENT_ID> \
#     --query id -o tsv --tenant 98a402ed-45fb-4cf8-bbfe-2b4c19bc36c7 \
#     --allow-no-subscriptions
#   Enables federated credential management for the deploy SP.
#   Note: existing credentials must be imported — see infra/tofu/README.md.
ciam_deploy_app_object_id = ""

# ciam_deploy_sp_object_id: Object ID of the "Canopex Tofu Deploy" SERVICE PRINCIPAL.
#   Find with: az ad sp show --id <TF_VAR_CIAM_DEPLOY_CLIENT_ID> \
#     --query id -o tsv --tenant 98a402ed-45fb-4cf8-bbfe-2b4c19bc36c7 \
#     --allow-no-subscriptions
#   Enables Tofu-managed app owner assertion (deploy SP owns Canopex SPA app).
ciam_deploy_sp_object_id = ""

environment                       = "dev"
location                          = "uksouth"
static_web_app_location           = "westeurope"
location_code                     = "uks"
project_code                      = "kmlsat"
log_retention_days                = 30
log_daily_cap_gb                  = 0.05
enable_event_grid_subscription    = false
enable_key_vault_purge_protection = true
container_image                   = "mcr.microsoft.com/azure-functions/python:4-python3.12"
default_tags = {
  cost-center = "dev"
}
budget_amount         = 10
budget_contact_emails = ["j.brewster@outlook.com"]
# NOTE: Apex domain is intentionally assigned to dev (the only deployed env).
# Clear this before applying prd.tfvars — a domain can only bind to one SWA.
custom_domain = "canopex.hrdcrprwn.com"
# One-time: import pre-existing custom domain into Tofu state.
# Set to false (or remove) after first successful apply.
import_custom_domain         = true
enable_azure_ai              = false
enable_stripe                = true
enable_cosmos_db             = true
cosmos_public_network_access = true # dev only — no VNet/private endpoint yet
function_max_instances       = 1
function_min_instances       = 0
orch_min_instances           = 0

# --- CIAM (Entra External ID) ---
# Public values; safe to commit.
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

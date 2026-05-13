environment                       = "prd"
location                          = "uksouth"
static_web_app_location           = "westeurope"
location_code                     = "uks"
project_code                      = "kmlsat"
log_retention_days                = 90
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

# --- CIAM (Entra External ID) ---
# Public values: visible in the deployed page HTML (canopex-ciam-config script).
# Tofu surfaces them as plain Function App app settings and a `ciam_page_config`
# output the SWA workflow injects into the page HTML at deploy time.
ciam_tenant_subdomain = "treesightauth"
ciam_tenant_id        = "92001438-8b42-4bd7-950f-0ed1775f87b7"
ciam_client_id        = "6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6"
ciam_api_audience     = "api://canopex"

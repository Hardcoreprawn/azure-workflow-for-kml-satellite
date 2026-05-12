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
# Tofu writes these into Key Vault secrets; the Function App reads them from KV
# refs and the SWA deploy step injects them into the page HTML at deploy time.
auth_mode         = "bearer_only"
ciam_tenant_id    = "92001438-8b42-4bd7-950f-0ed1775f87b7"
ciam_authority    = "https://treesightauth.ciamlogin.com/"
ciam_client_id    = "6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6"
ciam_api_audience = "api://canopex"

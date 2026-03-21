environment                       = "dev"
location                          = "uksouth"
static_web_app_location           = "westeurope"
location_code                     = "uks"
project_code                      = "kmlsat"
log_retention_days                = 30
enable_event_grid_subscription    = false
enable_key_vault_purge_protection = false
container_image                   = "mcr.microsoft.com/azure-functions/python:4-python3.12"
default_tags = {
  cost-center = "dev"
}
budget_amount         = 10
budget_contact_emails = ["alerts@jablab.dev"]
# Uncomment after creating CNAME in Cloudflare DNS:
# custom_domain        = "treesight.jablab.dev"
enable_azure_ai         = false

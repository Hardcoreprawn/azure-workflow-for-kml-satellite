environment                       = "prd"
location                          = "uksouth"
static_web_app_location           = "westeurope"
location_code                     = "uks"
project_code                      = "kmlsat"
log_retention_days                = 90
enable_event_grid_subscription    = false
enable_key_vault_purge_protection = true
container_image                   = "mcr.microsoft.com/azure-functions/python:4-python3.12"
default_tags = {
  cost-center = "prd"
}
budget_amount         = 50
budget_contact_emails = ["alerts@jablab.dev"]

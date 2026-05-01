environment                       = "dev"
location                          = "uksouth"
static_web_app_location           = "westeurope"
location_code                     = "uks"
project_code                      = "kmlsat"
log_retention_days                = 14
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

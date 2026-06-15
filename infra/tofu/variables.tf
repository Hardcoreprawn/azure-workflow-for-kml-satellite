variable "subscription_id" {
  description = "Azure subscription ID."
  type        = string
}

variable "deploy_principal_client_id" {
  description = "Azure client ID for the GitHub Actions OIDC deploy principal that is allowed to manage CMK keys."
  type        = string
}

variable "location" {
  description = "Azure region for deployment."
  type        = string
  default     = "uksouth"
}

variable "static_web_app_location" {
  description = "Azure region for Static Web App (must be one of supported regions)."
  type        = string
  default     = "westeurope"
}

variable "location_code" {
  description = "Short region code used in naming."
  type        = string
  default     = "uks"
}

variable "project_code" {
  description = "Short project code used in naming."
  type        = string
  default     = "kmlsat"

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.project_code))
    error_message = "project_code must be lowercase alphanumeric, length 3-12."
  }
}

variable "environment" {
  description = "Deployment environment code (dev or prd)."
  type        = string

  validation {
    condition     = contains(["dev", "prd"], var.environment)
    error_message = "environment must be one of: dev, prd."
  }
}

variable "log_retention_days" {
  description = "Log Analytics retention in days."
  type        = number
  default     = 90
}

variable "enable_event_grid_subscription" {
  description = "Enable Event Grid subscription creation in OpenTofu. Keep disabled when the deploy workflow owns webhook reconciliation."
  type        = bool
  default     = false
}

variable "enable_key_vault_purge_protection" {
  description = "Enable Key Vault purge protection."
  type        = bool
  default     = true
}

variable "container_image" {
  description = "Function app container image URI."
  type        = string
  default     = "mcr.microsoft.com/azure-functions/python:4-python3.12"
}

variable "orchestrator_image" {
  description = "Orchestrator function app container image URI (slim, no GDAL). #466"
  type        = string
  default     = "mcr.microsoft.com/azure-functions/python:4-python3.12"
}

variable "default_tags" {
  description = "Additional tags merged with required baseline tags."
  type        = map(string)
  default     = {}
}

variable "budget_amount" {
  description = "Monthly cost budget for the resource group in the subscription currency."
  type        = number
  default     = 10
}

variable "budget_contact_emails" {
  description = "Email addresses to receive budget alerts."
  type        = list(string)
}

variable "function_max_instances" {
  description = "Maximum number of Container Apps replicas for the Function App."
  type        = number
  default     = 3
}

variable "function_min_instances" {
  description = "Minimum always-ready instances for the compute Function App. Set to 0 to allow scale-to-zero; heavy GDAL image cold-starts are acceptable."
  type        = number
  default     = 0
}

variable "orch_min_instances" {
  description = "Minimum always-ready instances for the orchestrator Function App. Set to 1 to keep it warm so Durable orchestration and interactive HTTP requests never hit a cold-start 504."
  type        = number
  default     = 1
}

variable "ops_dashboard_key" {
  description = "Bearer token for /api/ops/dashboard. Empty = allow unauthenticated (dev only)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "log_daily_cap_gb" {
  description = "Log Analytics daily ingestion cap in GB. -1 for unlimited."
  type        = number
  default     = 1
}

variable "custom_domain" {
  description = "Full custom domain for the Static Web App (e.g. canopex.hrdcrprwn.com). Empty to skip."
  type        = string
  default     = ""
}

variable "import_custom_domain" {
  description = "Import a pre-existing SWA custom domain into state. Set true once, apply, then remove."
  type        = bool
  default     = false
}

variable "enable_azure_ai" {
  description = "Deploy Azure OpenAI resource for AI analysis (M1.6)."
  type        = bool
  default     = false
}

variable "azure_ai_location" {
  description = "Azure region for the OpenAI resource (must support the model)."
  type        = string
  default     = "swedencentral"
}

# --- Cosmos DB (M4 state persistence) ---

variable "enable_cosmos_db" {
  description = "Deploy Azure Cosmos DB for NoSQL (Serverless) for state persistence."
  type        = bool
  default     = false
}

variable "cosmos_public_network_access" {
  description = "Allow public network access to Cosmos DB. Enable only in dev (no VNet/private endpoint yet)."
  type        = bool
  default     = false
}

# --- Stripe billing (M4) ---

variable "enable_stripe" {
  description = "Enable Stripe billing app settings and stable Key Vault secret references."
  type        = bool
  default     = false
}

variable "billing_allowed_users" {
  description = "Comma-separated user IDs allowed to use real Stripe billing (feature gate). These users also get tier emulation access."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tier_emulation_allowed_users" {
  description = "Comma-separated user IDs allowed to use tier emulation without billing access (optional; billing_allowed_users get emulation implicitly)."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Email notifications (Azure Communication Services) ---

variable "enable_email" {
  description = "Deploy Azure Communication Services for email notifications."
  type        = bool
  default     = false
}

variable "notification_email" {
  description = "Email address to receive contact-form and system notifications."
  type        = string
  default     = ""
}

# --- CIAM (Entra External ID) bearer-token auth (Issue #709) ---
#
# Auth is bearer-only by design (see treesight.security.auth). The values below
# are *public* — they ship in the deployed page HTML and in JWTs the SPA hands
# to the API — so they live in committed tfvars rather than Key Vault.
# Tofu surfaces them as plain Function App app settings and as a
# `ciam_page_config` output the SWA workflow injects into HTML at deploy time.

variable "ciam_tenant_subdomain" {
  description = "Entra External ID tenant subdomain (the bit before .ciamlogin.com). The CIAM authority URL is computed as https://<subdomain>.ciamlogin.com/. Public; safe to commit."
  type        = string
  default     = ""
}

variable "ciam_tenant_id" {
  description = "Azure Entra tenant ID (GUID) for CIAM app registration. Required by MSAL for tenant-scoped token validation. Public; safe to commit."
  type        = string
  default     = ""
}

variable "ciam_api_audience" {
  description = "API audience (app ID URI) from CIAM app registration, e.g. api://canopex. Public; safe to commit."
  type        = string
  default     = ""
}

variable "ciam_client_id" {
  description = "Client ID (application ID) of the CIAM SPA app registration. Public; safe to commit."
  type        = string
  default     = ""
}

variable "ciam_deploy_client_id" {
  description = "Client ID of the service principal in the CIAM tenant used by CI/CD to manage the app registration via OIDC. Requires a federated credential in the CIAM tenant for this GitHub repo/environment."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ciam_app_object_id" {
  description = "Object ID of the CIAM SPA app registration in the CIAM tenant. Required to bring the app registration under Tofu state (azuread_application_registration). Find with: az ad app show --id <ciam_client_id> --query id -o tsv --tenant <ciam_tenant_id> --allow-no-subscriptions. Leave empty to fall back to data source (read-only) mode."
  type        = string
  default     = ""
}

variable "ciam_deploy_app_object_id" {
  description = "Object ID of the deploy SP's app registration in the CIAM tenant. Required to manage federated identity credentials for the GitHub Actions deploy SP. Find with: az ad app show --id <ciam_deploy_client_id> --query id -o tsv --tenant <ciam_tenant_id> --allow-no-subscriptions. Leave empty to skip federated credential management."
  type        = string
  default     = ""
}

variable "ciam_deploy_sp_object_id" {
  description = "Object ID of the deploy SP's service principal in the CIAM tenant. Required to assert the deploy SP as an owner of the SPA app registration. Find with: az ad sp show --id <ciam_deploy_client_id> --query id -o tsv --tenant <ciam_tenant_id> --allow-no-subscriptions. Leave empty to skip app owner assertion."
  type        = string
  default     = ""
}

# Cross-variable validation: all four required CIAM tfvars must be populated.
# Cannot be expressed in a per-variable validation block (those may only
# reference the validated variable itself), so enforced here as a plan-time
# precondition that fails fast with a descriptive error.
resource "terraform_data" "validate_ciam_vars" {
  lifecycle {
    precondition {
      condition = (
        var.ciam_tenant_subdomain != "" &&
        var.ciam_tenant_id != "" &&
        var.ciam_api_audience != "" &&
        var.ciam_client_id != ""
      )
      error_message = "ciam_tenant_subdomain, ciam_tenant_id, ciam_api_audience, and ciam_client_id must all be non-empty (set in environments/<env>.tfvars)."
    }
  }
}

# ciam_deploy_client_id is independently optional: when unset, Tofu skips
# managing the CIAM SPA app's redirect URIs (azuread_application_redirect_uris
# count = 0), and the azuread provider is not configured. This is the documented
# fallback for cost-estimate runs or environments where the deploy SP has not
# been bootstrapped yet.

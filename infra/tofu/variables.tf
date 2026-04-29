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
  description = "Full custom domain for the Static Web App (e.g. treesight.jablab.dev). Empty to skip."
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
  description = "Comma-separated user IDs allowed to use real Stripe billing (feature gate)."
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

# --- CIAM / Bearer Token Auth (Issue #709) ---

variable "auth_mode" {
  description = "Auth mode. Must be bearer_only (JWT only)."
  type        = string
  default     = "bearer_only"

  validation {
    condition     = var.auth_mode == "bearer_only"
    error_message = "auth_mode must be bearer_only."
  }
}

variable "ciam_authority" {
  description = "Azure Entra CIAM authority endpoint (https://login.microsoftonline.com/<tenant>). Required when auth_mode is 'bearer_only'."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ciam_tenant_id" {
  description = "Azure Entra tenant ID for CIAM app registration. Required when auth_mode is 'bearer_only'."
  type        = string
  default     = ""
  sensitive   = true
}

variable "ciam_api_audience" {
  description = "API audience (app ID URI) from CIAM app registration. Required when auth_mode is 'bearer_only'."
  type        = string
  default     = ""
  sensitive   = true
}

# Cross-variable validation: all three CIAM variables must be set when auth_mode
# enables CIAM token flows. Cannot be expressed in a variable validation block
# (which may only reference the validated variable itself), so enforced here as a
# plan-time precondition that fails fast with a descriptive error.
resource "terraform_data" "validate_ciam_auth_vars" {
  lifecycle {
    precondition {
      condition = (
        !contains(["dual", "bearer_only"], var.auth_mode) ||
        (var.ciam_authority != "" && var.ciam_tenant_id != "" && var.ciam_api_audience != "")
      )
      error_message = "ciam_authority, ciam_tenant_id, and ciam_api_audience must all be non-empty when auth_mode is 'dual' or 'bearer_only'."
    }
  }
}

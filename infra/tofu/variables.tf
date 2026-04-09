variable "subscription_id" {
  description = "Azure subscription ID."
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

# --- Entra External ID (CIAM) authentication (M2.1) ---

variable "ciam_tenant_name" {
  description = "CIAM tenant name (the prefix before .onmicrosoft.com). Empty to disable auth."
  type        = string
  default     = ""
}

variable "ciam_client_id" {
  description = "CIAM app registration client ID for the SPA + API."
  type        = string
  default     = ""
}

variable "ciam_client_secret" {
  description = "CIAM app registration client secret for SWA built-in auth OIDC code flow. Must be set when ciam_tenant_name is non-empty."
  type        = string
  default     = ""
  sensitive   = true
}

# --- Stripe billing (M4) ---

variable "enable_stripe" {
  description = "Enable Stripe billing app settings and stable Key Vault secret references."
  type        = bool
  default     = false
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

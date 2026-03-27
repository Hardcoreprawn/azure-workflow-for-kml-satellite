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

# --- Stripe billing (M4) ---

variable "enable_stripe" {
  description = "Enable Stripe billing infrastructure (Key Vault secrets, app settings)."
  type        = bool
  default     = false
}

variable "stripe_api_key" {
  description = "Stripe secret API key. Stored in Key Vault, never in app settings."
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret. Stored in Key Vault."
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_price_id_pro_gbp" {
  description = "Stripe Price ID for the Pro subscription plan (GBP)."
  type        = string
  default     = ""
}

variable "stripe_price_id_pro_usd" {
  description = "Stripe Price ID for the Pro subscription plan (USD)."
  type        = string
  default     = ""
}

variable "stripe_price_id_pro_eur" {
  description = "Stripe Price ID for the Pro subscription plan (EUR)."
  type        = string
  default     = ""
}

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

variable "environment" {
  description = "One environment per independently custodied bootstrap state."
  type        = string

  validation {
    condition     = contains(["dev", "prd"], var.environment)
    error_message = "environment must be dev or prd; preview environments cannot bootstrap shared trust."
  }
}

variable "subscription_id" {
  description = "Owner-approved subscription for this bootstrap."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a UUID."
  }
}

variable "tenant_id" {
  description = "Subscription tenant; this root does not administer CIAM."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be a UUID."
  }
}

variable "location" {
  description = "Owner-approved Azure region; no region is selected implicitly."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9]+$", var.location))
    error_message = "location must be a nonempty Azure region identifier; live availability needs separate verification."
  }
}

variable "project_code" {
  description = "Short project code, consistent with the existing infrastructure root."
  type        = string
  default     = "kmlsat"

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.project_code))
    error_message = "project_code must be lowercase alphanumeric, length 3-12."
  }
}

variable "enable_github_oidc" {
  description = "Owner activation only after verifying layer-specific GitHub environment protections."
  type        = bool
  default     = false
}

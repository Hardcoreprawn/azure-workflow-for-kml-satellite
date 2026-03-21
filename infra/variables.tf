# ─────────────────────────────────────────────────────────────
# Variables for TreeSight Azure infrastructure
# ─────────────────────────────────────────────────────────────

variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westeurope"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "project" {
  description = "Project name (used in resource naming)"
  type        = string
  default     = "treesight"
}

variable "custom_domain" {
  description = "Custom domain for the static web app (e.g. treesight.jablab.dev)"
  type        = string
  default     = ""
}

variable "docker_image_tag" {
  description = "Docker image tag for the functions container"
  type        = string
  default     = "latest"
}

variable "demo_valet_token_secret" {
  description = "Secret key for valet token signing"
  type        = string
  sensitive   = true
}

variable "budget_contact_email" {
  description = "Email address for cost budget alerts"
  type        = string
}

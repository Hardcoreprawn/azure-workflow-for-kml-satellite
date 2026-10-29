variable "application_phase" {
  description = "Offline declarations: disabled -> namespace -> custody -> encryption. Owner-verified permission/network gates remain separate."
  type        = string
  default     = "disabled"
  nullable    = false

  validation {
    condition     = contains(["disabled", "namespace", "custody", "encryption"], var.application_phase) && (var.application_phase == "disabled" || var.bootstrap_phase == "state")
    error_message = "Use disabled, namespace, custody or encryption; application declarations require the completed bootstrap state phase."
  }
}

variable "application_bootstrap_json" {
  description = "Exact approved raw bytes of bootstrap_contract v1 exported after state creation; never raw state."
  type        = string
  default     = ""
  nullable    = false

  validation {
    condition     = var.application_phase == "disabled" || length(var.application_bootstrap_json) > 0
    error_message = "Application declarations require the explicit immutable bootstrap JSON artifact."
  }
}

variable "application_bootstrap_sha256" {
  description = "Independently approved SHA256 of the exact bootstrap artifact bytes, including whitespace."
  type        = string
  default     = ""
}

variable "application_revisions" {
  description = "Explicit reviewed producer and policy commit revisions; these are not readiness claims."
  type = object({
    governance = string
    foundation = string
    policy     = string
  })
  default = {
    governance = ""
    foundation = ""
    policy     = ""
  }
}

variable "application_artifacts" {
  description = "Ordered raw immutable stage JSON strings: [] for namespace, namespace/prerequisites for custody, then custody/key for encryption."
  type        = list(string)
  default     = []
  nullable    = false

  validation {
    condition = length(var.application_artifacts) == lookup({
      disabled = 0, namespace = 0, custody = 2, encryption = 4
    }, var.application_phase, 0)
    error_message = "Application phase cannot skip or omit earlier artifacts."
  }
}

variable "application_allowed_ip_ranges" {
  description = "Explicit application-vault egress approval, restricted to a subset of the already validated bootstrap public IPv4 ranges."
  type        = set(string)
  default     = []

  validation {
    condition     = (var.application_phase == "disabled" || length(var.application_allowed_ip_ranges) > 0) && length(setsubtract(var.application_allowed_ip_ranges, var.bootstrap_allowed_ip_ranges)) == 0
    error_message = "Explicit application vault egress must be a nonempty subset of approved bootstrap public IPv4 ranges."
  }
}

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

  validation {
    condition     = !var.enable_github_oidc || var.bootstrap_phase == "state"
    error_message = "GitHub trust can only be activated after the keyed state phase."
  }
}

variable "bootstrap_phase" {
  description = "Advance identity -> key -> state only after owner-verified permissions; no fixed propagation sleeps."
  type        = string
  default     = "identity"

  validation {
    condition     = contains(["identity", "key", "state"], var.bootstrap_phase)
    error_message = "bootstrap_phase must be identity, key or state."
  }
}

variable "bootstrap_operator_object_id" {
  description = "Explicitly approved bootstrap key custodian; must match the authenticated operator, never a deployment identity."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.bootstrap_operator_object_id))
    error_message = "bootstrap_operator_object_id must be a UUID."
  }
}

variable "bootstrap_allowed_ip_ranges" {
  description = "Owner-approved public IPv4 egress addresses/CIDRs for operator and state runners; default denies data-plane access."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for address in var.bootstrap_allowed_ip_ranges :
      can(regex("^[0-9.]+(/[0-9]+)?$", address)) &&
      (can(cidrhost(address, 0)) || can(cidrhost("${address}/32", 0))) &&
      !can(regex("/(0+|31|32)$", address)) &&
      !can(regex("^(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.)", address))
    ])
    error_message = "Use public IPv4 addresses or /1-/30 CIDRs, never RFC1918, IPv6 or /0; specify single IPs without /32."
  }

  validation {
    condition     = var.bootstrap_phase == "identity" || length(var.bootstrap_allowed_ip_ranges) > 0
    error_message = "Key/state phases require explicitly approved operator/runner egress ranges."
  }
}

variable "context_path" {
  description = "Independently approved immutable expected-context JSON, not values inferred from a handoff."
  type        = string
}
variable "bootstrap_path" {
  description = "Exact immutable bootstrap v1 bytes. Never raw upstream state."
  type        = string
}
variable "artifacts" {
  description = "Ordered raw application-governance artifact paths, ending at this phase's predecessor."
  type        = list(string)
}
variable "phase" {
  description = "Acyclic foundation phase. Each advancement requires fresh, separately authorized permission/network evidence."
  type        = string
  default     = "prerequisites"
  validation {
    condition     = contains(["prerequisites", "key", "storage"], var.phase)
    error_message = "Foundation phase must be prerequisites, key, or storage."
  }
}
variable "writes_enabled" {
  description = "Closed by default. An explicit declaration gate only, not cloud authorization or permission propagation."
  type        = bool
  default     = false
}
variable "approved_storage_ip_ranges" {
  description = "Owner-approved public egress IPv4 addresses/CIDRs; no implied hosted-runner access."
  type        = set(string)
  default     = []
  validation {
    condition = alltrue([
      for value in var.approved_storage_ip_ranges :
      can(cidrhost(strcontains(value, "/") ? value : "${value}/32", 0)) &&
      !strcontains(value, ":") &&
      try(tonumber(split("/", value)[1]) >= 8, true)
    ])
    error_message = "Approve explicit IPv4 egress (CIDR prefix >= 8); do not allow the whole internet."
  }
}

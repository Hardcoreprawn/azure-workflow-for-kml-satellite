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
    condition     = contains(["prerequisites", "key", "storage", "cosmos-key", "cosmos"], var.phase)
    error_message = "Foundation phase must be prerequisites, key, storage, cosmos-key or cosmos."
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
      can(regex("^[0-9.]+(/[0-9]+)?$", value)) &&
      (can(cidrhost(value, 0)) || can(cidrhost("${value}/32", 0))) &&
      !can(regex("^(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.)", value)) &&
      try(tonumber(split("/", value)[1]) >= 8 && tonumber(split("/", value)[1]) <= 30, true)
    ])
    error_message = "Approve public IPv4 addresses or /8-/30 CIDRs, never RFC1918 or IPv6; specify single IPs without /32."
  }
}

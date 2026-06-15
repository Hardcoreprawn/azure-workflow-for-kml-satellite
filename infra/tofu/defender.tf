# ---------------------------------------------------------------------------
# Defender for Cloud plan pricing tiers
#
# Rationale matrix (post-cleanup, 2026-05-18 — issue #850):
#
# | Plan                       | Tier     | Subplan        | Rationale                              |
# |----------------------------|----------|----------------|----------------------------------------|
# | AppServices                | Standard | —              | Active FAs + SWA; threat detection on  |
# | StorageAccounts            | Standard | PerTransaction | Active storage (real data); malware    |
# | KeyVaults                  | Standard | PerTransaction | Active KV (real secrets); alert on key |
# | Discovery                  | Standard | —              | CSPM mandatory foundation              |
# | FoundationalCspm           | Standard | —              | CSPM mandatory foundation              |
# | VirtualMachines            | Free     | —              | No VMs in this subscription            |
# | SqlServers                 | Free     | —              | No Azure SQL in this subscription      |
# | SqlServerVirtualMachines   | Free     | —              | No SQL VMs in this subscription        |
# | KubernetesService          | Free     | —              | No AKS in this subscription            |
# | ContainerRegistry          | Free     | —              | No ACR in this subscription            |
# | Arm                        | Free     | —              | Low value for dev; ARM activity logged |
# | Dns                        | Free     | —              | No public DNS zones in scope           |
# | OpenSourceRelationalDatabases | Free     | —              | No OSS RDB in this subscription        |
# | Containers                 | Free     | —              | No containers outside Function Apps    |
# | CosmosDbs                  | Free     | —              | Serverless Cosmos; no sensitive PII    |
# | Api                        | Free     | —              | No API Management in this subscription |
#
# Pinning every plan here means `tofu apply` enforces the agreed state and
# prevents silent re-enablement via Portal clicks or `az security pricing`
# manual commands.
# ---------------------------------------------------------------------------

# --- Active (Standard) plans ---

resource "azurerm_security_center_subscription_pricing" "app_services" {
  tier          = "Standard"
  resource_type = "AppServices"
}

resource "azurerm_security_center_subscription_pricing" "storage_accounts" {
  tier          = "Standard"
  resource_type = "StorageAccounts"
  subplan       = "PerTransaction"
}

resource "azurerm_security_center_subscription_pricing" "key_vaults" {
  tier          = "Standard"
  resource_type = "KeyVaults"
  subplan       = "PerTransaction"
}

resource "azurerm_security_center_subscription_pricing" "discovery" {
  tier          = "Standard"
  resource_type = "Discovery"
}

resource "azurerm_security_center_subscription_pricing" "foundational_cspm" {
  tier          = "Standard"
  resource_type = "FoundationalCspm"
}

# --- Unused / low-value plans pinned to Free ---

resource "azurerm_security_center_subscription_pricing" "virtual_machines" {
  tier          = "Free"
  resource_type = "VirtualMachines"
}

resource "azurerm_security_center_subscription_pricing" "sql_servers" {
  tier          = "Free"
  resource_type = "SqlServers"
}

resource "azurerm_security_center_subscription_pricing" "sql_server_virtual_machines" {
  tier          = "Free"
  resource_type = "SqlServerVirtualMachines"
}

resource "azurerm_security_center_subscription_pricing" "kubernetes_service" {
  tier          = "Free"
  resource_type = "KubernetesService"
}

resource "azurerm_security_center_subscription_pricing" "container_registry" {
  tier          = "Free"
  resource_type = "ContainerRegistry"
}

resource "azurerm_security_center_subscription_pricing" "arm" {
  tier          = "Free"
  resource_type = "Arm"
}

resource "azurerm_security_center_subscription_pricing" "dns" {
  tier          = "Free"
  resource_type = "Dns"
}

resource "azurerm_security_center_subscription_pricing" "open_source_relational_databases" {
  tier          = "Free"
  resource_type = "OpenSourceRelationalDatabases"
}

resource "azurerm_security_center_subscription_pricing" "containers" {
  tier          = "Free"
  resource_type = "Containers"
}

resource "azurerm_security_center_subscription_pricing" "cosmos_dbs" {
  tier          = "Free"
  resource_type = "CosmosDbs"
}

resource "azurerm_security_center_subscription_pricing" "api" {
  tier          = "Free"
  resource_type = "Api"
}

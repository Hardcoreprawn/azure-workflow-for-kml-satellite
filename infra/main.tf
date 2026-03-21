# ─────────────────────────────────────────────────────────────
# TreeSight — Azure infrastructure (OpenTofu)
#
# Resources:
#   - Resource Group
#   - Container Registry (ACR)
#   - Storage Account (blob)
#   - Key Vault
#   - Log Analytics + Application Insights
#   - Container Apps Environment + Container App (Functions)
#   - Static Web App (website)
#   - Budget alert
# ─────────────────────────────────────────────────────────────

locals {
  name_prefix = "${var.project}-${var.environment}"
  # Storage account names: alphanumeric, 3-24 chars
  storage_name = replace("${var.project}${var.environment}sa", "-", "")
  acr_name     = replace("${var.project}${var.environment}acr", "-", "")
  tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "opentofu"
  }
}

# ── Resource Group ──────────────────────────────────────────

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name_prefix}"
  location = var.location
  tags     = local.tags
}

# ── Container Registry ──────────────────────────────────────

resource "azurerm_container_registry" "acr" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = true
  tags                = local.tags
}

# ── Storage Account ─────────────────────────────────────────

resource "azurerm_storage_account" "main" {
  name                     = local.storage_name
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  blob_properties {
    cors_rule {
      allowed_headers    = ["*"]
      allowed_methods    = ["GET", "HEAD"]
      allowed_origins    = ["*"]
      exposed_headers    = ["Content-Length", "Content-Type"]
      max_age_in_seconds = 3600
    }
  }

  tags = local.tags
}

resource "azurerm_storage_container" "kml_input" {
  name                 = "kml-input"
  storage_account_id   = azurerm_storage_account.main.id
}

resource "azurerm_storage_container" "pipeline_output" {
  name                 = "pipeline-output"
  storage_account_id   = azurerm_storage_account.main.id
}

resource "azurerm_storage_container" "pipeline_payloads" {
  name                 = "pipeline-payloads"
  storage_account_id   = azurerm_storage_account.main.id
}

# ── Key Vault ───────────────────────────────────────────────

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                        = "kv-${local.name_prefix}"
  resource_group_name         = azurerm_resource_group.main.name
  location                    = azurerm_resource_group.main.location
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  soft_delete_retention_days  = 7
  purge_protection_enabled    = false
  enable_rbac_authorization   = true

  tags = local.tags
}

resource "azurerm_key_vault_secret" "valet_secret" {
  name         = "demo-valet-token-secret"
  value        = var.demo_valet_token_secret
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.deployer_kv_admin]
}

# Grant the deployer (current identity) Key Vault Secrets Officer
resource "azurerm_role_assignment" "deployer_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# ── Log Analytics + Application Insights ────────────────────

resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                = "ai-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.tags
}

# ── Container Apps ──────────────────────────────────────────

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.name_prefix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

resource "azurerm_container_app" "functions" {
  name                         = "ca-${local.name_prefix}"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  registry {
    server               = azurerm_container_registry.acr.login_server
    username             = azurerm_container_registry.acr.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.acr.admin_password
  }

  secret {
    name  = "storage-connection"
    value = azurerm_storage_account.main.primary_connection_string
  }

  secret {
    name  = "appinsights-key"
    value = azurerm_application_insights.main.connection_string
  }

  secret {
    name  = "valet-secret"
    value = var.demo_valet_token_secret
  }

  template {
    min_replicas = 0
    max_replicas = 3

    container {
      name   = "functions"
      image  = "${azurerm_container_registry.acr.login_server}/${var.project}:${var.docker_image_tag}"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "FUNCTIONS_WORKER_RUNTIME"
        value = "python"
      }
      env {
        name        = "AzureWebJobsStorage"
        secret_name = "storage-connection"
      }
      env {
        name  = "AzureWebJobsFeatureFlags"
        value = "EnableWorkerIndexing"
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-key"
      }
      env {
        name  = "IMAGERY_PROVIDER"
        value = "planetary_computer"
      }
      env {
        name  = "IMAGERY_RESOLUTION_TARGET_M"
        value = "0.5"
      }
      env {
        name  = "IMAGERY_MAX_CLOUD_COVER_PCT"
        value = "20.0"
      }
      env {
        name  = "AOI_BUFFER_M"
        value = "100.0"
      }
      env {
        name  = "AOI_MAX_AREA_HA"
        value = "10000.0"
      }
      env {
        name        = "DEMO_VALET_TOKEN_SECRET"
        secret_name = "valet-secret"
      }
      env {
        name  = "DEMO_VALET_TOKEN_TTL_SECONDS"
        value = "86400"
      }
      env {
        name  = "DEMO_VALET_TOKEN_MAX_USES"
        value = "3"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 80
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

# ── Static Web App ──────────────────────────────────────────

resource "azurerm_static_web_app" "website" {
  name                = "swa-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = local.tags
}

# ── Budget Alert ────────────────────────────────────────────

data "azurerm_subscription" "current" {}

resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "budget-${local.name_prefix}"
  subscription_id = data.azurerm_subscription.current.id

  amount     = 30
  time_grain = "Monthly"

  time_period {
    start_date = "2026-04-01T00:00:00Z"
  }

  notification {
    enabled   = true
    threshold = 80
    operator  = "GreaterThanOrEqualTo"

    contact_emails = [var.budget_contact_email]
  }

  notification {
    enabled   = true
    threshold = 100
    operator  = "GreaterThanOrEqualTo"

    contact_emails = [var.budget_contact_email]
  }
}

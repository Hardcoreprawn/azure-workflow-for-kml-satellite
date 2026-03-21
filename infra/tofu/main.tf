resource "azurerm_resource_group" "main" {
  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}

resource "random_string" "storage_suffix" {
  length  = 4
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_storage_account" "main" {
  name                            = substr(replace("st${var.project_code}${var.environment}${random_string.storage_suffix.result}", "-", ""), 0, 24)
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  access_tier                     = "Hot"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true
  tags                            = local.tags
}

resource "azurerm_storage_container" "kml_input" {
  name                  = "kml-input"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "kml_output" {
  name                  = "kml-output"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "deployments" {
  name                  = "deployments"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "pipeline_payloads" {
  name                  = "pipeline-payloads"
  storage_account_id    = azurerm_storage_account.main.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "main" {
  storage_account_id = azurerm_storage_account.main.id

  rule {
    name    = "delete-offloaded-payloads-7d"
    enabled = true
    filters {
      prefix_match = ["pipeline-payloads/payloads/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 7
      }
    }
  }

  rule {
    name    = "archive-raw-imagery-180d"
    enabled = true
    filters {
      prefix_match = ["kml-output/imagery/raw/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = 180
      }
    }
  }

  rule {
    name    = "archive-raw-imagery-365d"
    enabled = true
    filters {
      prefix_match = ["kml-output/imagery/raw/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_archive_after_days_since_modification_greater_than = 365
      }
    }
  }
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = local.names.log_analytics_workspace
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                = local.names.app_insights
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.tags
}

resource "azurerm_monitor_metric_alert" "failed_requests" {
  name                = "alert-${local.name_suffix}-failed-requests"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_application_insights.main.id]
  description         = "Alert when failed request volume exceeds threshold."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT5M"
  enabled             = true

  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "requests/failed"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 5
  }

  tags = local.tags
}

resource "azurerm_monitor_metric_alert" "high_latency" {
  name                = "alert-${local.name_suffix}-high-latency"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_application_insights.main.id]
  description         = "Alert when average request latency is elevated."
  severity            = 3
  frequency           = "PT5M"
  window_size         = "PT5M"
  enabled             = true

  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "requests/duration"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 5000
  }

  tags = local.tags
}

resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "budget-${local.name_suffix}"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.budget_contact_emails
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.budget_contact_emails
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = var.budget_contact_emails
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}

resource "azurerm_key_vault" "main" {
  name                          = local.names.key_vault
  location                      = azurerm_resource_group.main.location
  resource_group_name           = azurerm_resource_group.main.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  purge_protection_enabled      = var.enable_key_vault_purge_protection
  soft_delete_retention_days    = 90
  rbac_authorization_enabled    = true
  public_network_access_enabled = true
  tags                          = local.tags
}

# --- Azure OpenAI for AI analysis (M1.6) ---

resource "azurerm_cognitive_account" "openai" {
  count                 = var.enable_azure_ai ? 1 : 0
  name                  = "oai-${local.name_suffix}"
  location              = var.azure_ai_location
  resource_group_name   = azurerm_resource_group.main.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-${local.name_suffix}"
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "gpt4o_mini" {
  count                = var.enable_azure_ai ? 1 : 0
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.openai[0].id

  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18"
  }

  sku {
    name     = "Standard"
    capacity = 8 # 8K tokens-per-minute
  }
}

resource "azurerm_container_app_environment" "main" {
  name                       = local.names.container_apps_environment
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

# Function App on Container Apps is provisioned via ARM type Microsoft.Web/sites
# because this configuration is not fully represented in azurerm resources.
resource "azapi_resource" "function_app" {
  type      = "Microsoft.Web/sites@2024-04-01"
  parent_id = azurerm_resource_group.main.id
  name      = local.names.function_app
  location  = azurerm_resource_group.main.location
  tags      = local.tags

  identity {
    type = "SystemAssigned"
  }

  body = {
    kind = "functionapp,linux,container,azurecontainerapps"
    properties = {
      managedEnvironmentId = azurerm_container_app_environment.main.id
      httpsOnly            = true
      siteConfig = {
        linuxFxVersion = "DOCKER|${var.container_image}"
        cors = {
          allowedOrigins = concat(
            [
              "http://localhost:1111",
              "https://${azurerm_static_web_app.main.default_host_name}",
              "https://*.azurestaticapps.net",
            ],
            var.custom_domain != "" ? ["https://${var.custom_domain}"] : []
          )
          supportCredentials = false
        }
        appSettings = concat([
          {
            name  = "AzureWebJobsStorage"
            value = azurerm_storage_account.main.primary_connection_string
          },
          {
            name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
            value = azurerm_application_insights.main.connection_string
          },
          {
            name  = "FUNCTIONS_WORKER_RUNTIME"
            value = "python"
          },
          {
            name  = "FUNCTIONS_EXTENSION_VERSION"
            value = "~4"
          },
          {
            name  = "AzureFunctionsJobHost__extensions__durableTask__storageProvider__type"
            value = "AzureStorage"
          },
          {
            name  = "KEY_VAULT_URI"
            value = azurerm_key_vault.main.vault_uri
          },
          {
            name  = "KEYVAULT_URL"
            value = azurerm_key_vault.main.vault_uri
          },
          {
            name  = "DEFAULT_INPUT_CONTAINER"
            value = "kml-input"
          },
          {
            name  = "DEFAULT_OUTPUT_CONTAINER"
            value = "kml-output"
          },
          {
            name  = "IMAGERY_PROVIDER"
            value = "planetary_computer"
          }
        ], var.enable_azure_ai ? [
          {
            name  = "AZURE_AI_ENDPOINT"
            value = azurerm_cognitive_account.openai[0].endpoint
          },
          {
            name  = "AZURE_AI_API_KEY"
            value = azurerm_cognitive_account.openai[0].primary_access_key
          },
          {
            name  = "AZURE_AI_DEPLOYMENT"
            value = "gpt-4o-mini"
          }
        ] : [])
      }
    }
  }

  response_export_values = ["id", "name", "properties.defaultHostName"]
}

resource "azurerm_static_web_app" "main" {
  name                = local.names.static_web_app
  location            = var.static_web_app_location
  resource_group_name = azurerm_resource_group.main.name
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = local.tags
}

# --- Custom domain (M1.5) ---

data "azurerm_dns_zone" "main" {
  count               = var.custom_domain != "" ? 1 : 0
  name                = var.dns_zone_name
  resource_group_name = var.dns_zone_resource_group
}

resource "azurerm_dns_cname_record" "static_web_app" {
  count               = var.custom_domain != "" ? 1 : 0
  name                = var.custom_domain_prefix
  zone_name           = data.azurerm_dns_zone.main[0].name
  resource_group_name = data.azurerm_dns_zone.main[0].resource_group_name
  ttl                 = 3600
  record              = azurerm_static_web_app.main.default_host_name
}

resource "time_sleep" "dns_propagation" {
  count           = var.custom_domain != "" ? 1 : 0
  create_duration = "60s"
  depends_on      = [azurerm_dns_cname_record.static_web_app]
}

resource "azurerm_static_web_app_custom_domain" "main" {
  count             = var.custom_domain != "" ? 1 : 0
  static_web_app_id = azurerm_static_web_app.main.id
  domain_name       = var.custom_domain
  validation_type   = "cname-delegation"

  depends_on = [time_sleep.dns_propagation]
}

resource "azurerm_role_assignment" "storage_blob_data_contributor" {
  scope                = azurerm_storage_account.main.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azapi_resource.function_app.identity[0].principal_id
}

resource "azurerm_role_assignment" "key_vault_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azapi_resource.function_app.identity[0].principal_id
}

resource "azapi_resource" "event_grid_system_topic" {
  type      = "Microsoft.EventGrid/systemTopics@2024-06-01-preview"
  parent_id = azurerm_resource_group.main.id
  name      = local.names.event_grid_system_topic
  location  = azurerm_resource_group.main.location
  tags      = local.tags

  body = {
    properties = {
      source    = azurerm_storage_account.main.id
      topicType = "Microsoft.Storage.StorageAccounts"
    }
  }
}

resource "azapi_resource_action" "function_host_keys" {
  type        = "Microsoft.Web/sites@2024-04-01"
  resource_id = azapi_resource.function_app.id
  action      = "host/default/listKeys"
  method      = "POST"

  response_export_values = ["masterKey", "systemKeys.eventgrid_extension", "systemKeys.eventgridextensionconfig_extension"]
}

locals {
  eventgrid_key = coalesce(
    try(azapi_resource_action.function_host_keys.output.systemKeys.eventgrid_extension, null),
    try(azapi_resource_action.function_host_keys.output.systemKeys.eventgridextensionconfig_extension, null),
    try(azapi_resource_action.function_host_keys.output.masterKey, null)
  )
}

resource "azapi_resource" "event_grid_subscription" {
  count = var.enable_event_grid_subscription ? 1 : 0

  type      = "Microsoft.EventGrid/systemTopics/eventSubscriptions@2024-06-01-preview"
  parent_id = azapi_resource.event_grid_system_topic.id
  name      = local.names.event_grid_subscription

  body = {
    properties = {
      destination = {
        endpointType = "WebHook"
        properties = {
          endpointUrl                   = "https://${azapi_resource.function_app.output.properties.defaultHostName}/runtime/webhooks/eventgrid?functionName=kml_blob_trigger&code=${local.eventgrid_key}"
          maxEventsPerBatch             = 1
          preferredBatchSizeInKilobytes = 64
        }
      }
      filter = {
        includedEventTypes     = ["Microsoft.Storage.BlobCreated"]
        subjectEndsWith        = ".kml"
        isSubjectCaseSensitive = false
      }
      eventDeliverySchema = "EventGridSchema"
      retryPolicy = {
        maxDeliveryAttempts      = 30
        eventTimeToLiveInMinutes = 1440
      }
    }
  }

  depends_on = [azapi_resource_action.function_host_keys]
}

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
  daily_quota_gb      = var.log_daily_cap_gb
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

resource "azurerm_monitor_action_group" "ops" {
  name                = "ag-${local.name_suffix}-ops"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "ops"
  enabled             = true
  tags                = local.tags

  dynamic "email_receiver" {
    for_each = var.budget_contact_emails
    content {
      name                    = "ops-email-${email_receiver.key}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
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

  action {
    action_group_id = azurerm_monitor_action_group.ops.id
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

  action {
    action_group_id = azurerm_monitor_action_group.ops.id
  }

  tags = local.tags
}

# --- Availability test: ping the site every 5 minutes from 5 regions ---
resource "azurerm_application_insights_standard_web_test" "site_ping" {
  name                    = "webtest-${local.name_suffix}-site-ping"
  resource_group_name     = azurerm_resource_group.main.name
  location                = azurerm_resource_group.main.location
  application_insights_id = azurerm_application_insights.main.id
  frequency               = 300 # seconds (5 minutes)
  timeout                 = 30
  enabled                 = true
  geo_locations           = ["emea-nl-ams-azr", "emea-gb-db3-azr", "us-va-ash-azr", "us-il-ch1-azr", "apac-sg-sin-azr"]
  tags                    = local.tags

  request {
    url = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${azurerm_static_web_app.main.default_host_name}"
  }

  validation_rules {
    expected_status_code = 200
  }
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

# --- Stripe secrets in Key Vault (M4) ---

resource "azurerm_key_vault_secret" "stripe_api_key" {
  count        = var.enable_stripe ? 1 : 0
  name         = "stripe-api-key"
  value        = coalesce(var.stripe_api_key, "PLACEHOLDER")
  key_vault_id = azurerm_key_vault.main.id
  tags         = local.tags

  lifecycle { ignore_changes = [value] }
}

resource "azurerm_key_vault_secret" "stripe_webhook_secret" {
  count        = var.enable_stripe ? 1 : 0
  name         = "stripe-webhook-secret"
  value        = coalesce(var.stripe_webhook_secret, "PLACEHOLDER")
  key_vault_id = azurerm_key_vault.main.id
  tags         = local.tags

  lifecycle { ignore_changes = [value] }
}

resource "azurerm_key_vault_secret" "stripe_price_id_pro_gbp" {
  count        = var.enable_stripe ? 1 : 0
  name         = "stripe-price-id-pro-gbp"
  value        = coalesce(var.stripe_price_id_pro_gbp, "PLACEHOLDER")
  key_vault_id = azurerm_key_vault.main.id
  tags         = local.tags

  lifecycle { ignore_changes = [value] }
}

resource "azurerm_key_vault_secret" "stripe_price_id_pro_usd" {
  count        = var.enable_stripe ? 1 : 0
  name         = "stripe-price-id-pro-usd"
  value        = coalesce(var.stripe_price_id_pro_usd, "PLACEHOLDER")
  key_vault_id = azurerm_key_vault.main.id
  tags         = local.tags

  lifecycle { ignore_changes = [value] }
}

resource "azurerm_key_vault_secret" "stripe_price_id_pro_eur" {
  count        = var.enable_stripe ? 1 : 0
  name         = "stripe-price-id-pro-eur"
  value        = coalesce(var.stripe_price_id_pro_eur, "PLACEHOLDER")
  key_vault_id = azurerm_key_vault.main.id
  tags         = local.tags

  lifecycle { ignore_changes = [value] }
}

# --- Azure Communication Services Email ---

resource "azurerm_communication_service" "main" {
  count               = var.enable_email ? 1 : 0
  name                = local.names.communication_service
  resource_group_name = azurerm_resource_group.main.name
  data_location       = "Europe"
  tags                = local.tags
}

resource "azurerm_email_communication_service" "main" {
  count               = var.enable_email ? 1 : 0
  name                = local.names.email_service
  resource_group_name = azurerm_resource_group.main.name
  data_location       = "Europe"
  tags                = local.tags
}

resource "azurerm_email_communication_service_domain" "azure_managed" {
  count             = var.enable_email ? 1 : 0
  name              = "AzureManagedDomain"
  email_service_id  = azurerm_email_communication_service.main[0].id
  domain_management = "AzureManaged"
  tags              = local.tags
}

# Link the email domain to the communication service so the SDK can send mail
resource "azapi_update_resource" "acs_link_email" {
  count       = var.enable_email ? 1 : 0
  type        = "Microsoft.Communication/communicationServices@2023-04-01"
  resource_id = azurerm_communication_service.main[0].id

  body = {
    properties = {
      linkedDomains = [azurerm_email_communication_service_domain.azure_managed[0].id]
    }
  }
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

  # Workaround: azapi v2 "Missing Resource Identity After Update" bug.
  # The ARM API omits identity from update responses, crashing the provider.
  # Body changes (image, app settings) are handled by az CLI in the deploy
  # pipeline to avoid triggering updates that hit this bug.
  lifecycle {
    ignore_changes = [identity, body]
  }

  body = {
    kind = "functionapp,linux,container,azurecontainerapps"
    properties = {
      managedEnvironmentId = azurerm_container_app_environment.main.id
      httpsOnly            = true
      functionAppConfig = {
        scaleAndConcurrency = {
          maximumInstanceCount = var.function_max_instances
        }
      }
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
          },
          {
            name  = "REQUIRE_AUTH"
            value = var.environment == "prd" ? "true" : ""
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
          ] : [], var.ciam_tenant_name != "" ? [
          {
            name  = "CIAM_TENANT_NAME"
            value = var.ciam_tenant_name
          },
          {
            name  = "CIAM_CLIENT_ID"
            value = var.ciam_client_id
          },
          {
            name  = "CIAM_AUDIENCE"
            value = var.ciam_client_id
          }
          ] : [], var.enable_stripe ? [
          {
            name  = "STRIPE_API_KEY"
            value = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.stripe_api_key[0].versionless_id})"
          },
          {
            name  = "STRIPE_WEBHOOK_SECRET"
            value = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.stripe_webhook_secret[0].versionless_id})"
          },
          {
            name  = "STRIPE_PRICE_ID_PRO_GBP"
            value = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.stripe_price_id_pro_gbp[0].versionless_id})"
          },
          {
            name  = "STRIPE_PRICE_ID_PRO_USD"
            value = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.stripe_price_id_pro_usd[0].versionless_id})"
          },
          {
            name  = "STRIPE_PRICE_ID_PRO_EUR"
            value = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.stripe_price_id_pro_eur[0].versionless_id})"
          }
        ] : [], var.enable_email ? [
          {
            name  = "COMMUNICATION_SERVICES_CONNECTION_STRING"
            value = azurerm_communication_service.main[0].primary_connection_string
          },
          {
            name  = "EMAIL_SENDER_ADDRESS"
            value = "DoNotReply@${azurerm_email_communication_service_domain.azure_managed[0].mail_from_sender_domain}"
          },
          {
            name  = "NOTIFICATION_EMAIL"
            value = var.notification_email
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
  sku_tier            = "Standard"
  sku_size            = "Standard"
  tags                = local.tags
}

# --- Linked backend (disabled): the linkedBackends ARM API returns 500
# for Function Apps on Container Apps (kind: azurecontainerapps).
# See #282 — the frontend falls back to calling the Function App directly
# via the hostname injected at deploy time in /api-config.json.
# Re-enable if Azure adds Container Apps Function App support. ---

# --- Custom domain (M1.5) ---
# Prerequisites (manual, one-time):
#   1. Create a CNAME record in your DNS provider (e.g. Cloudflare):
#      treesight.jablab.dev → <SWA default hostname>
#   2. Wait for DNS propagation, then run tofu apply.

resource "azurerm_static_web_app_custom_domain" "main" {
  count             = var.custom_domain != "" ? 1 : 0
  static_web_app_id = azurerm_static_web_app.main.id
  domain_name       = var.custom_domain
  validation_type   = "cname-delegation"
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

# Allow the deployer (tofu apply / setup scripts) to manage secrets
resource "azurerm_role_assignment" "key_vault_secrets_officer" {
  count                = var.enable_stripe ? 1 : 0
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
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

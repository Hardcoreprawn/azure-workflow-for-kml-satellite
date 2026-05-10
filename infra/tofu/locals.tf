locals {
  name_suffix = "${var.project_code}-${var.environment}"

  names = {
    resource_group             = "rg-${local.name_suffix}"
    log_analytics_workspace    = "log-${local.name_suffix}"
    app_insights               = "appi-${local.name_suffix}"
    key_vault                  = "kv-${local.name_suffix}"
    container_apps_environment = "cae-${local.name_suffix}"
    function_app               = "func-${local.name_suffix}"
    function_app_orch          = "func-${local.name_suffix}-orch"
    event_grid_system_topic    = "evgt-${local.name_suffix}"
    event_grid_subscription    = "evgs-kml-upload"
    static_web_app             = "stapp-${local.name_suffix}-site"
    communication_service      = "acs-${local.name_suffix}"
    email_service              = "ecs-${local.name_suffix}"
    cosmos_account             = "cosmos-${local.name_suffix}"
  }

  required_tags = {
    project     = "kml-satellite"
    environment = var.environment
    managed-by  = "opentofu"
    owner       = "platform"
  }

  tags = merge(local.required_tags, var.default_tags)

  # Use exact browser origins so Function App and Blob Storage stay in sync.
  # SWA preview hostnames are intentionally excluded because blob CORS must
  # enumerate concrete origins for the direct browser SAS upload path.
  browser_allowed_origins = distinct(concat(
    var.environment == "prd" ? [] : [
      "http://localhost:1111",
      "http://localhost:4280",
    ],
    ["https://${azurerm_static_web_app.main.default_host_name}"],
    var.custom_domain != "" ? ["https://${var.custom_domain}"] : []
  ))

  primary_site_url = var.custom_domain != "" ? "https://${var.custom_domain}" : "https://${azurerm_static_web_app.main.default_host_name}"

  # SPA redirect URIs to register in the CIAM app registration.
  # Must include every origin+path that canopex-auth.js pageRedirectUri() may produce.
  # Mirrors the browser_allowed_origins pattern: localhost ports for non-prd,
  # SWA default hostname always, and the custom domain when configured.
  ciam_spa_redirect_uris = distinct(concat(
    var.environment == "prd" ? [] : [
      "http://localhost:1111/",
      "http://localhost:1111/app/",
      "http://localhost:1111/eudr/",
      "http://localhost:4280/",
      "http://localhost:4280/app/",
      "http://localhost:4280/eudr/",
    ],
    [
      "https://${azurerm_static_web_app.main.default_host_name}/",
      "https://${azurerm_static_web_app.main.default_host_name}/app/",
      "https://${azurerm_static_web_app.main.default_host_name}/eudr/",
    ],
    var.custom_domain != "" ? [
      "https://${var.custom_domain}/",
      "https://${var.custom_domain}/app/",
      "https://${var.custom_domain}/eudr/",
    ] : []
  ))
}

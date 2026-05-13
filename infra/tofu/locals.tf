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

  # CIAM authority URL is computed from the tenant subdomain + tenant ID.
  # Entra External ID tenants use https://<subdomain>.ciamlogin.com/<tenant-id>/.
  # The tenant-id segment is REQUIRED: MSAL.js validates the id_token `iss`
  # claim against the authority, and CIAM's issuer is tenant-scoped
  # (https://<tenant-id>.ciamlogin.com/<tenant-id>/v2.0). Without the tenant
  # path, handleRedirectPromise() rejects post-login and no session is
  # established. The trailing slash matters for MSAL's authority parsing.
  ciam_authority = (
    var.ciam_tenant_subdomain != "" && var.ciam_tenant_id != ""
    ? "https://${var.ciam_tenant_subdomain}.ciamlogin.com/${var.ciam_tenant_id}/"
    : ""
  )

  # Page-level CIAM bootstrap config, injected into website HTML at deploy time
  # via `tofu output -raw ciam_page_config`. The SWA workflow substitutes this
  # JSON into the canopex-ciam-config <script> tag. Keep field names in sync
  # with website/js/canopex-auth.js readPageConfig().
  ciam_page_config_json = jsonencode({
    clientId    = var.ciam_client_id
    authority   = local.ciam_authority
    tenantId    = var.ciam_tenant_id
    apiAudience = var.ciam_api_audience
  })

  # SPA redirect URIs to register in the CIAM app registration.
  # Must include every origin+path that canopex-auth.js pageRedirectUri() may produce.
  # Mirrors the browser_allowed_origins pattern: localhost ports for non-prd,
  # SWA default hostname always, and the custom domain when configured.
  # MSAL always redirects to the origin root ('/') — canopex-auth.js uses
  # window.location.origin + '/' as redirectUri. MSAL's navigateToLoginRequestUrl
  # (default: true) returns the user to the originating page automatically.
  # Only root URIs need CIAM registration; no per-page entries required.
  ciam_spa_redirect_uris = distinct(concat(
    var.environment == "prd" ? [] : [
      "http://localhost:1111/",
      "http://localhost:4280/",
    ],
    [
      "https://${azurerm_static_web_app.main.default_host_name}/",
    ],
    var.custom_domain != "" ? [
      "https://${var.custom_domain}/",
    ] : []
  ))
}

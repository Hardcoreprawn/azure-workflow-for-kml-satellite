locals {
  name_suffix = "${var.project_code}-${var.environment}"

  names = {
    resource_group             = "rg-${local.name_suffix}"
    log_analytics_workspace    = "log-${local.name_suffix}"
    app_insights               = "appi-${local.name_suffix}"
    key_vault                  = "kv-${local.name_suffix}"
    container_apps_environment = "cae-${local.name_suffix}"
    function_app               = "func-${local.name_suffix}"
    event_grid_system_topic    = "evgt-${local.name_suffix}"
    event_grid_subscription    = "evgs-kml-upload"
    static_web_app             = "stapp-${local.name_suffix}-site"
    swa_identity               = "id-${local.name_suffix}-swa"
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
}

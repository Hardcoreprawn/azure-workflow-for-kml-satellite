# Operational Readiness Assessment

**Date:** March 8, 2026  
**Environment:** `dev` (OpenTofu-managed)  
**Scope:** Monitoring, Testing, Validation, Operational Procedures

---

## Executive Summary

| Category | Status | Grade | Critical Gaps |
| -------- | ------ | ----- | ------------- |
| **Infrastructure Monitoring** | 🟡 Partial | B- | No alert notifications configured |
| **Application Health** | ✅ Good | A- | No automated health monitoring |
| **Testing Coverage** | ✅ Good | A | No post-deployment smoke tests |
| **Operational Procedures** | 🔴 Missing | D | No runbook, no incident response |
| **Event Grid Monitoring** | 🔴 Missing | F | No delivery failure tracking |
| **Cost Management** | 🔴 Missing | F | No budget alerts |

**Overall Grade:** C+ — Functionally deployed but not production-ready for on-call operations.

---

## 1. Infrastructure Monitoring 🟡

### ✅ Deployed

```hcl
# Application Insights + Log Analytics
resource "azurerm_application_insights" "main"
resource "azurerm_log_analytics_workspace" "main"

# Metric Alerts
resource "azurerm_monitor_metric_alert" "failed_requests"  # Threshold: > 5 in 5min
resource "azurerm_monitor_metric_alert" "high_latency"     # Threshold: > 5s avg
```

**Strengths:**

- Application Insights configured with connection string in Function App
- Structured logging with correlation IDs (Durable Functions instance ID)
- Live metrics stream available
- Request/dependency telemetry auto-collected

### 🔴 Critical Gap: No Action Group

**Problem:** Alerts exist but have no configured notification channels.

**Impact:** When thresholds breach, Azure fires alerts but **nobody is notified**.

**Fix Required:**

```hcl
resource "azurerm_monitor_action_group" "ops_team" {
  name                = "ag-kmlsat-ops"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "kmlsat-ops"

  email_receiver {
    name          = "ops-email"
    email_address = "ops@example.com"
  }

  webhook_receiver {
    name        = "teams-webhook"
    service_uri = "https://outlook.office.com/webhook/..."
  }
}

# Wire alerts to action group
resource "azurerm_monitor_metric_alert" "failed_requests" {
  # ... existing config ...
  action {
    action_group_id = azurerm_monitor_action_group.ops_team.id
  }
}
```

---

## 2. Application Health Endpoints ✅

### Implemented

| Endpoint | Purpose | Checks |
| ---------- | --------- | -------- |
| `GET /api/health` | Liveness probe | Function host can start |
| `GET /api/readiness` | Readiness probe | Config valid, blob storage accessible, Key Vault reachable |

**Code Location:** [`function_app.py:337-423`](d:\projects\azure-workflow-for-kml-satellite\function_app.py)

**Strengths:**

- Proper liveness/readiness separation (Kubernetes-style)
- Readiness checks all external dependencies
- Returns structured JSON with status + dependency states

### 🔴 Gap: No Automated Health Monitoring

**Problem:** Health endpoints exist but nothing calls them on a schedule to detect outages.

**Fix Required:**

```hcl
resource "azurerm_application_insights_standard_web_test" "health_check" {
  name                    = "webtest-health-check"
  location                = azurerm_resource_group.main.location
  resource_group_name     = azurerm_resource_group.main.name
  application_insights_id = azurerm_application_insights.main.id

  geo_locations = ["emea-nl-ams-azr", "emea-gb-db3-azr"]
  frequency     = 300  # 5 minutes
  timeout       = 30
  enabled       = true

  request {
    url                              = "https://${azapi_resource.function_app.output.properties.defaultHostName}/api/readiness"
    follow_redirects_enabled         = false
    parse_dependent_requests_enabled = false
    http_verb                        = "GET"
  }

  validation_rules {
    expected_status_code        = 200
    ssl_cert_remaining_lifetime = 7
    ssl_check_enabled           = true

    content {
      content_match      = "\"status\":\"healthy\""
      ignore_case        = true
      pass_if_text_found = true
    }
  }
}

# Alert on availability test failures
resource "azurerm_monitor_metric_alert" "health_check_failure" {
  name                = "alert-${local.name_suffix}-health-failure"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_application_insights.main.id]
  description         = "Alert when health check availability falls below 80%"
  severity            = 1  # Critical
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "microsoft.insights/components"
    metric_name      = "availabilityResults/availabilityPercentage"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 80
  }

  action {
    action_group_id = azurerm_monitor_action_group.ops_team.id
  }
}
```

---

## 3. Testing Coverage ✅

### Unit Tests (40+ test files)

**Location:** [`tests/unit/`](d:\projects\azure-workflow-for-kml-satellite\tests\unit)

**Coverage:**

- ✅ Activity functions (parse_kml, prepare_aoi, acquire_imagery, etc.)
- ✅ Models (contracts, payloads, exceptions)
- ✅ Orchestrator phases and error handling
- ✅ Provider abstraction and factory pattern
- ✅ Circuit breaker
- ✅ Payload offloading
- ✅ Blob path generation
- ✅ Input validation
- ✅ Architecture compliance (Dockerfile, host.json, deploy workflow)
- ✅ Health endpoints

**Strengths:**

- Parametrized tests covering edge cases
- Strict type validation in tests
- Defensive coding patterns tested (NoneType guards, validation)

### Integration Tests

**Location:** [`tests/integration/`](d:\projects\azure-workflow-for-kml-satellite\tests\integration)

**Coverage:**

- ✅ E2E pipeline validation with type-safe fake provider
- ✅ Multi-tenant isolation tests
- ✅ Contract enforcement (input/output shapes)

### 🔴 Gap: No Post-Deployment Smoke Tests

**Problem:** CI validates code locally but doesn't verify deployed infrastructure is operational.

**Impact:** OpenTofu apply succeeds but you don't know if:

- Function app can reach storage
- Event Grid subscription is delivering events
- Durable Functions orchestration can start

**Fix Required:**

```yaml
# .github/workflows/tofu-apply.yml (add job after apply)
smoke-test:
  needs: [apply]
  runs-on: ubuntu-latest
  steps:
    - name: Health Check
      run: |
        echo "Testing function app health endpoint..."
        response=$(curl -s -o /dev/null -w "%{http_code}" \
          https://func-kmlsat-dev.wittycliff-6f794588.uksouth.azurecontainerapps.io/api/health)
        if [ "$response" != "200" ]; then
          echo "❌ Health check failed: $response"
          exit 1
        fi
        echo "✅ Health check passed"

    - name: Readiness Check
      run: |
        echo "Testing function app readiness..."
        response=$(curl -s https://func-kmlsat-dev.wittycliff-6f794588.uksouth.azurecontainerapps.io/api/readiness)
        echo "Response: $response"
        if ! echo "$response" | jq -e '.status == "healthy"' > /dev/null; then
          echo "❌ Readiness check failed"
          exit 1
        fi
        echo "✅ Readiness check passed"

    - name: Upload Test KML
      run: |
        echo "Uploading test KML to trigger Event Grid..."
        az storage blob upload \
          --account-name stkmlsatdevqzq4 \
          --container-name kml-input \
          --name "smoke-test-$(date +%Y%m%d%H%M%S).kml" \
          --file tests/data/01_single_polygon_orchard.kml \
          --auth-mode login

        echo "✅ Upload succeeded - Event Grid should trigger orchestration"
        echo "   Monitor orchestration at: https://portal.azure.com/#view/.../func-kmlsat-dev"
```

---

## 4. Event Grid Monitoring 🔴

### ✅ Deployed

```hcl
resource "azapi_resource" "event_grid_system_topic"
resource "azapi_resource" "event_grid_subscription"  # Filter: *.kml
```

**Event Grid Destination:** `endpointType=AzureFunction`, `resourceId=/subscriptions/.../providers/Microsoft.Web/sites/<app>/functions/kml_blob_trigger`

### 🔴 Critical Gaps

**No monitoring for:**

1. Event Grid delivery failures (webhook 4xx/5xx)
2. Subscription health (dead letter queue)
3. Event latency (time from blob create → function trigger)
4. Dropped events

**Fix Required:**

```hcl
# Dead letter queue for failed events
resource "azurerm_storage_container" "event_grid_deadletter" {
  name                  = "event-grid-deadletter"
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# Update Event Grid subscription with dead letter config
resource "azapi_resource" "event_grid_subscription" {
  # ... existing config ...
  body = {
    properties = {
      # ... existing destination/filter ...
      deadLetterDestination = {
        endpointType = "StorageBlob"
        properties = {
          resourceId  = azurerm_storage_account.main.id
          blobContainerName = azurerm_storage_container.event_grid_deadletter.name
        }
      }
    }
  }
}

# Alert on Event Grid delivery failures
resource "azurerm_monitor_metric_alert" "event_grid_failures" {
  name                = "alert-${local.name_suffix}-eventgrid-failures"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azapi_resource.event_grid_system_topic.id]
  description         = "Alert when Event Grid has delivery failures"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.EventGrid/systemTopics"
    metric_name      = "DeliveryFailedCount"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 3
  }

  action {
    action_group_id = azurerm_monitor_action_group.ops_team.id
  }
}
```

---

## 5. Durable Functions Monitoring 🟡

### ✅ Auto-Collected Telemetry

- Orchestration start/complete events
- Activity function execution times
- Fan-out/fan-in parallelism metrics
- Retry attempts

**Query Examples (Application Insights):**

```kusto
// Failed orchestrations in last 24h
customEvents
| where timestamp > ago(24h)
| where name == "FunctionCompleted" and customDimensions.Category == "Orchestrator"
| where customDimensions.Status == "Failed"
| project timestamp, instanceId=customDimensions.InstanceId, error=customDimensions.Reason
| order by timestamp desc

// Activity timeouts
dependencies
| where timestamp > ago(24h)
| where type == "Azure Functions"
| where success == false and resultCode == "Timeout"
| summarize count() by name, bin(timestamp, 1h)
```

### 🔴 Gaps

**No alerts for:**

1. Orchestration failure rate spike
2. Activity timeout threshold
3. Queue depth backlog (too many pending orchestrations)

**Fix Required:**

```hcl
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "orchestration_failures" {
  name                = "alert-${local.name_suffix}-orch-failures"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"
  scopes               = [azurerm_application_insights.main.id]
  severity             = 2

  criteria {
    query = <<-QUERY
      customEvents
      | where name == "FunctionCompleted" and customDimensions.Category == "Orchestrator"
      | where customDimensions.Status == "Failed"
      | summarize FailureCount=count() by bin(timestamp, 5m)
      | where FailureCount > 5
    QUERY

    time_aggregation_method = "Count"
    threshold               = 1
    operator                = "GreaterThan"
  }

  action {
    action_groups = [azurerm_monitor_action_group.ops_team.id]
  }
}
```

---

## 6. Operational Runbook 🔴

### Status: DOES NOT EXIST

**Referenced in:** [`docs/reviews/UAT_VALIDATION.md`](d:\projects\azure-workflow-for-kml-satellite\docs\reviews\UAT_VALIDATION.md#L159)

**Required Sections:**

1. **Health Check Procedures** — How to verify system is operational
2. **Incident Triage** — How to diagnose failures (queries, dashboards)
3. **Recovery Procedures** — How to restart failed orchestrations
4. **Escalation Matrix** — Who to contact for what
5. **Common Issues** — Known problems and solutions

**Fix Required:** Create `docs/RUNBOOK.md` with operational procedures.

---

## 7. Cost Management 🔴

### Status: NO MONITORING

**Risk:** Uncontrolled spend from:

- Large KML uploads triggering excessive imagery orders
- Retry storms consuming Function App execution time
- Storage growth unchecked

**Fix Required:**

```hcl
resource "azurerm_consumption_budget_resource_group" "monthly" {
  name              = "budget-${local.name_suffix}-monthly"
  resource_group_id = azurerm_resource_group.main.id

  amount     = 100  # USD per month
  time_grain = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"

    contact_emails = [
      "ops@example.com"
    ]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"

    contact_emails = [
      "ops@example.com"
    ]
  }
}
```

---

## Summary: Priority Fixes

| Priority | Item | Effort | Impact |
| ---------- | ------ | -------- | -------- |
| 🔴 P0 | Action Group for alert notifications | 15 min | Nobody knows when things break |
| 🔴 P0 | Event Grid dead letter + failure alerts | 30 min | Silent event loss |
| 🔴 P0 | Operational runbook | 2-4 hours | Can't respond to incidents |
| 🟡 P1 | Automated health check monitoring | 30 min | Manual health verification |
| 🟡 P1 | Post-deployment smoke tests | 1 hour | Broken deploys go undetected |
| 🟡 P1 | Orchestration failure alerts | 30 min | Durable Functions failures not visible |
| 🟢 P2 | Cost budget alerts | 15 min | Overspend risk |

**Recommendation:** Implement P0 items before declaring production-ready.

---

## Verification Checklist

Before promoting to production:

- [ ] Action Group configured with on-call email/Teams webhook
- [ ] All metric alerts wired to Action Group
- [ ] Availability test pinging `/api/readiness` every 5 minutes
- [ ] Event Grid dead letter queue configured
- [ ] Event Grid delivery failure alerts active
- [ ] Orchestration failure rate alert configured
- [ ] Operational runbook created with triage procedures
- [ ] Cost budget set with 80%/100% notifications
- [ ] Post-deployment smoke test runs in CI/CD
- [ ] On-call rotation established (if applicable)

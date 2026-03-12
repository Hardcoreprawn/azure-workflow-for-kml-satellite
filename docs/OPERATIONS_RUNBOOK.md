# Operations Runbook

Issue: #18

## Deploy

1. Run CI checks.
2. Deploy infrastructure and app via GitHub Actions deploy workflow.
3. Verify Function host readiness using /api/health.
4. Verify Event Grid subscription reconciliation succeeds.

Reference: .github/workflows/deploy.yml and infra/tofu/README.md.

## Monitor

Primary telemetry:

- Application Insights traces/exceptions
- Durable orchestration status endpoint
- Azure Monitor alerts for failed requests and latency

Operational checks:

1. Query failed orchestration runs by instance_id.
2. Correlate instance_id with activity logs.
3. Verify artifact presence in output blob container.

## Troubleshoot Common Failures

### Orchestration never appears

1. Confirm Event Grid subscription exists and is healthy.
2. Confirm uploaded blob is in expected input container and has .kml suffix.
3. Check trigger logs for validation rejection.

### Orchestration failed in activity stage

1. Use /api/orchestrator/{instance_id} for stage/output summary.
2. Review activity-specific exceptions in App Insights.
3. Re-run with corrected input or configuration as needed.

### Provider transient failures

1. Confirm retry/backoff behavior in logs.
2. Wait for retries to complete before manual intervention.
3. Escalate if repeated failure exceeds operational threshold.

## Add New Imagery Provider Adapter

1. Implement ImageryProvider in kml_satellite/providers.
2. Implement search/order/poll/download with typed returns.
3. Register adapter in provider factory.
4. Add unit tests for success and error/retry paths.
5. Validate with integration tests before enabling in env config.

## Rotate Secrets

1. Rotate source secrets in Key Vault.
2. Validate managed identity role assignments still allow read.
3. Restart/redeploy function app if required for refresh.
4. Run /api/readiness and a live smoke upload to verify.

## Re-process Failed KML

1. Locate failed instance id and root cause.
2. Correct data/config issue.
3. Re-upload KML with a new blob name.
4. Confirm new orchestration reaches Completed and writes artifacts.

## Tune Processing Thresholds

Adjust via app settings and redeploy:

- AOI_BUFFER_M
- IMAGERY_RESOLUTION_TARGET_M
- IMAGERY_MAX_CLOUD_COVER_PCT
- AOI_MAX_AREA_HA

Validate changes with integration tests and one live sample upload.

# Operations Runbook

Issue: #18

## Deploy

1. Run CI checks.
2. Deploy infrastructure and app via GitHub Actions deploy workflow.
3. Verify Function host readiness using /api/health.
4. Verify Event Grid subscription reconciliation succeeds.

Reference: .github/workflows/deploy.yml and infra/tofu/README.md.

## Access Model

Anonymous operator endpoints:

- `GET /api/health`
- `GET /api/readiness`
- `GET /api/orchestrator/{instance_id}`

Protected endpoints (function/admin/ARM auth required):

- `POST /admin/host/status`
- `GET /admin/functions`
- Durable runtime admin endpoints under `/runtime/webhooks/durabletask/*`
- ARM `.../host/default/listKeys`

Responder verification path (remote):

1. Check `GET /api/health`.
2. Check `GET /api/readiness`.
3. Inspect `GET /api/orchestrator/{instance_id}` for stage state and artifact paths.
4. Verify artifact blobs exist in output storage.

Do not request or expose host/admin keys in incident channels unless absolutely required for break-glass operations.

## Deploy Smoke Checks (Issue #164)

The deploy workflow now emits a Post-Deploy Smoke Evidence section after rollout.

What it validates:

1. Anonymous contract still works (`/api/health`, `/api/readiness`, `/api/orchestrator/{instance_id}`).
2. Protected contract still holds (`/admin/*` and durable runtime endpoints deny unauthenticated calls, allow authenticated calls).
3. Durable orchestration diagnostics reach `Completed` for the selected smoke instance.
4. Metadata artifact paths reported by diagnostics exist in blob storage.

How to interpret failures:

1. `Anonymous ... expected 200` failure:
API surface regression, routing regression, or host startup degradation.
2. `unexpectedly accessible without auth` failure:
security boundary regression; treat as high priority and halt rollout.
3. `auth path failed (expected 200)` failure:
host key/bootstrap regression or protected runtime endpoint outage.
4. `Could not resolve smoke orchestration instance id` failure:
trigger path regression (Event Grid ingestion/runtime discovery) or durable query mismatch.
5. `did not reach Completed` or terminal failure status:
pipeline correctness regression in ingestion/acquisition/fulfillment stages.
6. `Expected smoke artifact missing` failure:
orchestrator diagnostics and storage outputs diverged or artifact write failed.

Responder action order for smoke failures:

1. Capture failing evidence block from the workflow summary.
2. Query `/api/orchestrator/{instance_id}` and inspect `output.artifacts`.
3. Cross-check App Insights using `instance_id` and stage-level exceptions.
4. Validate blob existence and RBAC/storage connectivity for the output container.

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

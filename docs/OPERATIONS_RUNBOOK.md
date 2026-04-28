# Operations Runbook

Issue: #18

## Quick Reference — Dev Environment

| Resource | Value |
| --- | --- |
| Site URL | `https://green-moss-0e849ac03.2.azurestaticapps.net` |
| Function App URL (public ingress) | `https://func-kmlsat-dev-orch.jollysea-48e72cf8.uksouth.azurecontainerapps.io` |
| Health check | `curl -sS https://func-kmlsat-dev-orch.jollysea-48e72cf8.uksouth.azurecontainerapps.io/api/health` |
| Readiness check | `curl -sS https://func-kmlsat-dev-orch.jollysea-48e72cf8.uksouth.azurecontainerapps.io/api/readiness` |
| API config | `curl -sS https://green-moss-0e849ac03.2.azurestaticapps.net/api-config.json` |
| Resource Group | `rg-kmlsat-dev` |
| Cosmos DB | `https://cosmos-kmlsat-dev.documents.azure.com:443/` |
| Auth | Transition mode: SWA principal (+ optional HMAC) by default; CIAM bearer JWT path available when enabled |
| Container image | `ghcr.io/hardcoreprawn/azure-workflow-for-kml-satellite:{sha}` |

**Note:** The SWA does not proxy `/api/*` — all API calls go directly to the Function App hostname (see Architecture Overview for details).

## Deploy

1. Run CI checks.
2. Deploy infrastructure and app via GitHub Actions deploy workflow.
3. Confirm Terraform-managed browser origins include the SWA default hostname and the production custom domain so both `/api/*` and direct blob SAS uploads pass CORS preflight.
4. Preview SWA hosts are not wildcard-allowed for blob uploads; if a preview environment needs browser uploads, add its exact origin through infra before rollout.
5. Verify Function host readiness using /api/health.
   Deploy workflow note: compute and orchestrator readiness probes run in parallel and both must pass.
6. Verify Event Grid subscription reconciliation succeeds.
7. Require post-readiness async smoke gate to pass (upload token → blob upload → orchestrator completion with a valid diagnostics payload shape).
8. `/api/analysis/submit` must reject unauthenticated callers before any upload or orchestration work begins.
9. For direct `analysis/` uploads created by `/api/analysis/submit`, rely on the HTTP submission path as the authoritative orchestration start; BlobCreated automation should only start storage-native uploads outside that prefix.
10. Treat Function App managed identity as a deploy contract (both apps must remain `SystemAssigned` with non-empty `principalId`); deploy fails fast if identity drifts.
11. Treat CLI-owned Function App body wiring as intentional (`image`, app settings, platform CORS, scale): `tofu` does not reconcile these fields because they are set and then contract-verified in deploy CI.

workflow_dispatch reproducibility controls for the async smoke gate:

- `smoke_poll_interval_seconds`
- `smoke_max_attempts`

CMK deploy note (dev and prod):

- Storage Account CMK rollout requires the configured GitHub Actions OIDC deploy principal to hold `Key Vault Crypto Officer` on the vault so OpenTofu can manage the CMK key lifecycle.
- CMK authoring is pinned to that explicit deploy principal; local applies must authenticate as the same principal instead of relying on the caller's personal identity.
- The infra stack assigns that role and waits for RBAC propagation before managing the key to avoid `ForbiddenByRbac` failures during `tofu apply`.

Reference: .github/workflows/deploy.yml and infra/tofu/README.md.

## Access Model

### Auth Transition Notes (#709 phase 1)

- `AUTH_MODE=legacy_principal` (default): endpoints authenticate via
 `X-MS-CLIENT-PRINCIPAL` (SWA) and, when configured, `X-Auth-Session` HMAC.
- `AUTH_MODE=dual`: Authorization bearer JWT validation is enabled while
 preserving the legacy SWA-principal fallback path.
- `AUTH_MODE=bearer_only`: Authorization bearer JWT is required for
 authenticated calls; legacy-principal-only calls are rejected.
- Bearer-capable modes (`dual` and `bearer_only`) require
 `CIAM_AUTHORITY`, `CIAM_TENANT_ID`, and `CIAM_API_AUDIENCE` app settings.

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

Expected Canopex application log shape in App Insights traces:

- Single-line JSON for the `treesight`, `blueprints`, and `function_app` logger families
- Stable top-level keys: `timestamp`, `level`, `logger`, `message`
- Optional correlation keys: `correlation_id`, `properties`, `exception`
- Pipeline helper fields appear under `properties`, including values such as `phase`, `step`, `instance_id`, and `blob_name`

Operational checks:

1. Query failed orchestration runs by instance_id.
2. Correlate instance_id with activity logs.
3. Verify artifact presence in output blob container.

If startup evidence is missing, query for `logger=function_app` first to confirm
the startup logging installer ran before config validation and replay-store setup.

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

### Function App in ImagePullBackOff

1. Check Function App app settings include `DOCKER_REGISTRY_SERVER_URL=ghcr.io`, `DOCKER_REGISTRY_SERVER_USERNAME=<ghcr pull principal>`, and `DOCKER_REGISTRY_SERVER_PASSWORD=<non-empty>`.
2. If password is empty or expired, redeploy via GitHub Actions to re-apply registry credentials.
3. Confirm the `dev` environment secret `GHCR_PULL_TOKEN` is present and valid (`read:packages` scope).
4. Confirm workflow pre-flight passed `GHCR_PULL_TOKEN` contract validation.
5. After recovery, restart Function App and verify `/api/health` returns 200.

## Add New Imagery Provider Adapter

1. Implement ImageryProvider in treesight/providers.
2. Implement search/order/poll/download with typed returns.
3. Register adapter in provider factory.
4. Add unit tests for success and error/retry paths.
5. Validate with integration tests before enabling in env config.

## Rotate Secrets

1. Rotate source secrets in Key Vault.
2. Validate managed identity role assignments still allow read.
3. Restart/redeploy function app if required for refresh.
4. Run /api/readiness and a live smoke upload to verify.

GHCR runtime pull credential:

1. Rotate GitHub PAT used by `GHCR_PULL_TOKEN` (environment `dev`) before expiry.
2. Ensure PAT has at least `read:packages` for `ghcr.io/hardcoreprawn/azure-workflow-for-kml-satellite`.
3. Trigger deploy workflow to push updated credential into Function App app settings.
4. Validate by scaling from zero and confirming no `ImagePullBackOff` events.

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

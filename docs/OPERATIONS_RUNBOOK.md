# Operations Runbook

Issue: #18

## Quick Reference — Dev Environment

Specific hostnames and resource identifiers for the dev environment are not
stored in this document; retrieve them from the Azure portal or from
`tofu output` after provisioning.  The patterns below follow
[INFRA_NAMING_STANDARD.md](INFRA_NAMING_STANDARD.md).

| Resource | Pattern |
| --- | --- |
| Site URL | Azure Static Web App default hostname (check Azure portal) |
| Function App URL (public ingress) | `https://func-kmlsat-dev-orch.<cae-suffix>.uksouth.azurecontainerapps.io` |
| Health check | `curl -sS <func-app-url>/api/health` |
| Readiness check | `curl -sS <func-app-url>/api/readiness` |
| API config | `curl -sS <swa-url>/api-config.json` |
| Resource Group | `rg-kmlsat-dev` |
| Cosmos DB | `https://cosmos-kmlsat-dev.documents.azure.com:443/` |
| Auth | CIAM bearer JWT (bearer-only; see CIAM config) via MSAL.js |
| Container image | `ghcr.io/hardcoreprawn/azure-workflow-for-kml-satellite:{sha}` |

**Note:** The SWA does not proxy `/api/*` — all API calls go directly to the Function App hostname (see Architecture Overview for details). Use `tofu output -raw function_app_orch_default_hostname` to retrieve the exact ingress hostname.

## Deploy

### Reset Mode (pipeline reset in progress)

During the pipeline reset there is **no cloud deployment**. Validation is
local-only and the deploy workflow is gated by a release-safety `preflight`
job in `.github/workflows/deploy.yml`:

- **Production is frozen.** Any `prd` target fails immediately at `preflight`.
  Lift by removing the prd guard step when ready to ship to production again.
- **Auto dev deploys are paused.** While the repo variable `DEPLOY_PAUSED=true`,
  a merge to `main` (CI success → `workflow_run`) will not deploy into the
  torn-down dev environment. Set `DEPLOY_PAUSED=false` to resume, or deploy
  deliberately via `workflow_dispatch`.

Local validation loop (no Azure):

1. `make dev-all` — starts Azurite, creates storage containers (`init-storage`), and starts the containerised Functions host + website together (single path, ADR 0005).
2. `make test` for the suite; `make smoke` for host health.
3. Exercise the pipeline end-to-end against Azurite with `make test-upload`.

When the reset lands and you are ready to deploy again: set `DEPLOY_PAUSED=false`,
remove the prd freeze guard, then follow the standard deploy steps below.

### Standard deploy

1. Run CI checks.
2. Confirm custom-domain ownership preflight is green (dev/prd must not claim the same non-empty domain unless a controlled transfer is explicitly approved).
3. Deploy infrastructure and app via GitHub Actions deploy workflow.
4. For a one-off production domain transfer, use `workflow_dispatch` with `allow_domain_transfer=true` and execute DNS validation + rollback checks before proceeding.
5. Confirm Terraform-managed browser origins include the SWA default hostname and the production custom domain so both `/api/*` and direct blob SAS uploads pass CORS preflight.
6. Preview SWA hosts are not wildcard-allowed for blob uploads; if a preview environment needs browser uploads, add its exact origin through infra before rollout.
7. Verify Function host readiness using /api/health.
   Deploy workflow note: compute and orchestrator readiness probes run in parallel and both must pass.
   Rollback note: a single canonical rollback step restores whichever app images were updated (compute, orchestrator, or both) and then health-checks both hosts.
8. Verify Event Grid subscription reconciliation succeeds.
9. Require post-readiness async smoke gate to pass (upload token → blob upload → orchestrator completion with a valid diagnostics payload shape).
10. `/api/analysis/submit` must reject unauthenticated callers before any upload or orchestration work begins.
11. For direct `analysis/` uploads created by `/api/analysis/submit`, rely on the HTTP submission path as the authoritative orchestration start; BlobCreated automation should only start storage-native uploads outside that prefix.
12. Treat Function App managed identity as a deploy contract (both apps must remain `SystemAssigned` with non-empty `principalId`); deploy fails fast if identity drifts.
13. Treat CLI-owned Function App body wiring as intentional (`image`, app settings, platform CORS, scale): `tofu` does not reconcile these fields because they are set and then contract-verified in deploy CI.

workflow_dispatch reproducibility controls for the async smoke gate:

- `smoke_poll_interval_seconds`
- `smoke_max_attempts`

CMK deploy note (dev and prod):

- Storage Account CMK rollout requires the configured GitHub Actions OIDC deploy principal to hold `Key Vault Crypto Officer` on the vault so OpenTofu can manage the CMK key lifecycle.
- CMK authoring is pinned to that explicit deploy principal; local applies must authenticate as the same principal instead of relying on the caller's personal identity.
- The infra stack assigns that role and waits for RBAC propagation before managing the key to avoid `ForbiddenByRbac` failures during `tofu apply`.

Reference: .github/workflows/deploy.yml and infra/tofu/README.md.

## Access Model

### Auth Model

- Bearer-only is the only supported mode (JWT in `Authorization: Bearer …`).
- Required app settings: `CIAM_AUTHORITY`, `CIAM_TENANT_ID`, `CIAM_API_AUDIENCE`.

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

## Smoke Tests

### Standard pipeline smoke (deployed environment)

```sh
python scripts/pipeline_smoke.py \
  --storage-account <account> \
  --orch-hostname   <func-hostname> \
  --resource-group  <rg> \
  --orch-app-name   <func-app>
```

Uses `tests/fixtures/sample.kml` by default (`--kml-file` to override).
Asserts `runtimeStatus == Completed` and prints `featureCount` / `aoiCount`.

### Duplicate-named AOI back-to-back smoke (local Azurite stack)

Validates that two consecutive pipeline runs with a KML containing
duplicate feature names both reach a terminal state without silent data
loss or key collisions.  This test guards against the flakiness class
described in issue #872.

Prerequisites:

```sh
make dev-all   # Start Azurite + containerised Functions host + website
```

Run:

```sh
make test-int-live
```

What it checks:

1. First submission of `tests/fixtures/duplicate_names.kml` reaches a terminal state.
2. Second (back-to-back) submission reaches a terminal state.
3. Both runs produce the **same** terminal status — no flakiness between submissions.
4. Both runs must complete successfully and report `aoiCount` equal to the input feature count (2).

The tests are skipped automatically when Azurite or the local Functions host
is not reachable, so they do not affect the standard `make test` suite. The
`make test-int-live` gate converts an all-skipped run into a failure so missing
dependencies cannot appear green.

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

### Function App write blocked by stuck ARM operation

Symptom in deploy logs:

- `Cannot modify this site because another operation is in progress`
- Usually appears during `Configure Function App` or `Configure Orchestrator Function App`

Responder actions:

1. Capture the workflow-emitted activity log table (`Microsoft.Web/sites/write` operation IDs + timestamps).
2. Retry the same write from Azure Portal once (portal path can clear backend lock state).
3. If lock persists for more than 1 hour, open an Azure Support ticket and attach the operation ID/correlation ID.
4. Re-run deploy after lock clears and confirm readiness checks (`/api/health`, `/api/readiness`) pass for both compute + orchestrator hosts.

Rollback/readiness note:

- Rollback image steps also require ARM writes; if the lock is active, rollback cannot proceed until Azure clears the operation.
- Treat the environment as unchanged until deploy resumes and the workflow readiness probes complete successfully.

### Agent PR checks stuck on `action_required` (no CI runs)

Symptom: a Copilot SWE-agent PR shows every workflow (CI, CodeQL, Security,
Require Linked Issue) as `action_required` and never executes, so the PR sits
unvalidated for days.

Cause: GitHub requires manual approval before workflows run on PRs from the
agent actor. Marking the PR ready or editing its body does **not** clear this —
only an approval or a maintainer-authored commit does.

Responder actions:

1. Preferred: open the PR's **Checks** tab and click **Approve and run** (or set
   Settings → Actions → General → "Require approval for" to a less restrictive
   option for the agent if this recurs constantly).
2. Quick unblock from CLI: push a maintainer-authored commit so the
   `synchronize` event runs CI without approval — e.g.
   `git commit --allow-empty -m "ci: re-trigger checks" && git push`.
3. The `/actions/runs/{id}/approve` REST endpoint only works for fork PRs and
   returns 403 for in-repo agent branches — do not rely on it.
4. Also confirm the PR links an issue (`Closes #NNN` in the body); the PR
   Watchdog flags `Linked issue: MISSING` and draft PRs as `READY_TO_PROMOTE`.

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

## Legacy/Compat Support Matrix

The following paths exist for backward compatibility with older document shapes.
They are **not** intentional long-term features; each one fires a
`LEGACY_COMPAT_HIT` warning log whenever it is actually exercised in production.
Once a path shows zero log hits over a sustained window (suggested: 30 days of
normal traffic), it is safe to open the linked removal issue.

| Path | Location | Why it exists | Safe-to-remove signal | Removal issue |
|------|----------|--------------|----------------------|---------------|
| Per-user `quota` field preservation | `treesight/security/users.py` `_preserve_quota_fields`; `treesight/security/orgs.py` `_set_user_org`, `_clear_user_org` | Accounting migrated from per-user counters to org-level counters in D3 of the domain-model overhaul (#1057). Shim kept to avoid resetting counters on user documents not yet backfilled. | `LEGACY_COMPAT_HIT per_user_quota_preserved` log message shows zero hits for ≥30 days | #1298 |
| `_resolve_legacy_user_org` | `treesight/security/orgs.py:389` | Fallback for user documents created before org-membership normalisation; these carry a bare `org_id` field instead of a full membership record. | `LEGACY_COMPAT_HIT legacy_user_org_resolved` log message shows zero hits for ≥30 days | #1300 |
| `year_a`/`year_b` dual-key support in AOI metrics | `treesight/pipeline/enrichment/aoi_metrics.py` `_worst_change` | Legacy callers emitted season-change entries with `year_a`/`year_b`; current schema uses `year_from`/`year_to`. Both shapes are accepted. | `LEGACY_COMPAT_HIT aoi_metrics_legacy_year_keys` log message shows zero hits for ≥30 days | #1299 |

### Querying the instrumentation signals

Using Application Insights / Azure Monitor:

```kusto
traces
| where message startswith "LEGACY_COMPAT_HIT"
| extend signal = extract(@"LEGACY_COMPAT_HIT (\S+)", 1, message)
| summarize count() by signal, bin(timestamp, 1d)
| order by timestamp desc
```

`summarize count()` only emits a row for (signal, day) combinations that
actually occurred — it never emits an explicit `count = 0` row. The
safe-to-remove signal is the **absence** of any row for a given `signal`
across the most recent N days (suggested: 30), not a row with count = 0.

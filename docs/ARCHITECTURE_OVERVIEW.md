# Architecture Overview

Issue: #18

## Deployed Components

The production pipeline is deployed as Azure Functions on Container Apps with event-driven orchestration.

### Naming Convention

All resources are named using `{prefix}-{project_code}-{environment}` where:

- `project_code` is set in `infra/tofu/environments/{env}.tfvars` (dev: `kmlsat`)
- `environment` is set per deployment (dev: `dev`)
- Prefixes follow Azure naming standards defined in `infra/tofu/locals.tf`

| Resource | Naming Pattern | Dev Value |
| --- | --- | --- |
| Resource Group | `rg-{code}-{env}` | `rg-kmlsat-dev` |
| Function App | `func-{code}-{env}` | `func-kmlsat-dev` |
| Static Web App | `stapp-{code}-{env}-site` | `stapp-kmlsat-dev-site` |
| Event Grid Topic | `evgt-{code}-{env}` | `evgt-kmlsat-dev` |
| Event Grid Sub | `evgs-kml-upload` | `evgs-kml-upload` |
| Key Vault | `kv-{code}-{env}` | `kv-kmlsat-dev` |
| Cosmos DB | `cosmos-{code}-{env}` | `cosmos-kmlsat-dev` |
| App Insights | `appi-{code}-{env}` | `appi-kmlsat-dev` |
| Log Analytics | `log-{code}-{env}` | `log-kmlsat-dev` |
| Container Apps Env | `cae-{code}-{env}` | `cae-kmlsat-dev` |
| Communication Svc | `acs-{code}-{env}` | `acs-kmlsat-dev` |
| Email Service | `ecs-{code}-{env}` | `ecs-kmlsat-dev` |

Additional fixed names:

- Input container: `kml-input`
- Output container: `kml-output`
- Durable task hub: `KmlSatelliteHub`

### Dev Environment Endpoints

| Endpoint | URL |
| --- | --- |
| **Site (SWA)** | `https://green-moss-0e849ac03.2.azurestaticapps.net` |
| **Function App** | `https://func-kmlsat-dev.jollysea-48e72cf8.uksouth.azurecontainerapps.io` |
| **Cosmos DB** | `https://cosmos-kmlsat-dev.documents.azure.com:443/` |

The SWA hostname is Azure-assigned (no custom domain currently configured).
The Function App runs on Azure Container Apps in `uksouth`; the SWA is in `westeurope`.

### API Routing

The SWA linked-backend integration is **disabled** (see `infra/tofu/main.tf` line ~739) because Azure's `linkedBackends` ARM API returns 500 for Function Apps on Container Apps.

Instead, the frontend calls the Function App directly using the hostname injected into `/api-config.json` at deploy time:

```text
GET https://green-moss-0e849ac03.2.azurestaticapps.net/api-config.json
→ {"apiBase": "https://func-kmlsat-dev.jollysea-48e72cf8.uksouth.azurecontainerapps.io", ...}
```

This means:

- `/api/*` routes through the SWA return **404** (expected)
- All API calls go directly to the Function App hostname
- CORS and CSP in `website/staticwebapp.config.json` allow `*.azurecontainerapps.io`

### Auth (CIAM)

- Tenant: `treesightauth.ciamlogin.com`
- Client ID: `6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6`
- Provider: Azure AD B2C / CIAM (MSAL.js in frontend)

### Deploy Pipeline

```text
Push to main → CI workflow → (on success) → Deploy workflow
                                              ├─ 1. Build & push container to GHCR
                                              ├─ 2. OpenTofu plan + apply (infra/tofu/)
                                              ├─ 3. Deploy Function App (az functionapp)
                                              ├─ 4. Deploy Static Web App (SWA token)
                                              ├─ 5. Reconcile Event Grid subscription
                                              └─ 6. Post-deploy smoke checks
```

Trigger: `workflow_run` on CI completion for `main`, or `workflow_dispatch`.
Concurrency: serialized per ref (no cancellation of in-progress deploys).
Config: `.github/workflows/deploy.yml`

## Data Flow

1. User uploads KML into input blob container.
2. Event Grid emits a BlobCreated event.
3. kml_blob_trigger validates event payload and starts kml_processing_orchestrator.
4. Orchestrator runs phase pipeline:
   - parse_kml
   - prepare_aoi + write_metadata
   - acquire_imagery + poll_order_suborchestrator + download_imagery + post_process_imagery
5. Metadata and imagery artifacts are written to output blob paths.
6. Operational diagnostics are available at /api/orchestrator/{instance_id}.

## Imagery Output Framing Policy (2026-03-12)

User-facing imagery outputs follow an AOI-first UX policy:

- Primary deliverable: regular framed outputs that fully contain each AOI feature.
- Default framing mode target: square frame with small configurable padding.
- MultiPolygon handling target: split into per-feature/per-polygon outputs by default.
- Optional artifact: composite overview image for context.
- Ground truth remains AOI geometry in metadata/contracts.

Backlog tracking:

- #176 (enhancement): implement regular framed output strategy and multipolygon split defaults.
- #177 (enhancement): add optional H3-derived analytical outputs without replacing AOI-first deliverables.
- #172 (bug): restore clipping pipeline path so framed/clipped outputs are generated from blob-backed imagery.

## Provider Adapter Boundary

The orchestrator calls provider adapters only through the ImageryProvider contract in kml_satellite/providers/base.py.

Required adapter methods:

- search(aoi, filters) -> list[SearchResult]
- order(scene_id) -> OrderId
- poll(order_id) -> OrderStatus
- download(order_id) -> BlobReference

This allows provider-specific logic to evolve without changing orchestration flow.

## Configuration Reference (Environment)

Core runtime settings:

- DEFAULT_INPUT_CONTAINER or KML_INPUT_CONTAINER
- DEFAULT_OUTPUT_CONTAINER or KML_OUTPUT_CONTAINER
- IMAGERY_PROVIDER
- IMAGERY_RESOLUTION_TARGET_M
- IMAGERY_MAX_CLOUD_COVER_PCT
- AOI_BUFFER_M
- AOI_MAX_AREA_HA
- KEYVAULT_URL
- AzureWebJobsStorage
- APPLICATIONINSIGHTS_CONNECTION_STRING

Validation and defaults are implemented in kml_satellite/core/config.py.

## Observability Surface

HTTP diagnostics:

- GET /api/health
- GET /api/readiness
- GET /api/orchestrator/{instance_id}

Structured logs include correlation and entity fields such as:

- instance, correlation_id
- blob, feature
- order_id, provider

## Deployment Model

Infrastructure is managed with OpenTofu under infra/tofu.

Deployment sequencing must ensure host readiness before Event Grid subscription enablement, to avoid webhook validation race conditions.

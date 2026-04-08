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

### API Routing — SWA as BFF (Backend-for-Frontend)

The SWA managed API is the **only public-facing API surface**. All browser API calls go through `/api/*` on the SWA. The Container Apps function app is never directly exposed to the browser for auth-gated operations.

```text
Browser ─── /api/* ──→ SWA Managed API (T1, always-warm)
                          │
                          ├── reads: Cosmos DB (analysis/history, billing/status)
                          ├── writes: Blob Storage SAS minting (upload/token)
                          └── async: Queue/Event Grid → Container Apps (T2/T3)
                                                          │
                                                          ├── Orchestrator (T2, scale-to-zero)
                                                          └── Compute (T3, heavy processing)
```

This means:

- `/api/*` routes are served by the SWA managed API — always warm, no cold-start
- All user-facing responses return fast — expensive backend work is async (queue/Event Grid)
- Container Apps only receives work via Event Grid blob triggers or queue messages
- No CORS complexity — everything is same-origin under the SWA hostname
- Container Apps can be network-locked to reject direct browser calls

No unauthenticated endpoints are exposed to browsers. Infrastructure probes (`/health`, `/readiness`) are internal to Container Apps (network-locked). The Stripe billing webhook uses its own signature verification. The `contact-form` endpoint is a pre-login rate-limited form carrying no user data.

#### Showcase vs Tiers

Two distinct concepts serve different purposes — do not conflate them:

| Concept | Auth | Processing | Purpose |
|---------|------|-----------|---------|
| **Showcase** | None (anonymous) | None — pre-computed static blobs from stock AOIs | Marketing. Let visitors see real output quality before signing up. |
| **Free tier** | SWA auth (authenticated) | Real — own KML/KMZ, low-res, seasonal cadence | Try the product. 5 runs, ≤5 AOIs, 30-day retention, no alerts, all manual. Negligible compute cost. |
| **Starter / Pro / Team / Enterprise** | SWA auth (authenticated) | Real — full pipeline, higher limits, richer features | Paid plans with increasing AOI counts, cadence, retention, exports, API access. |

The **showcase** is served from `imagery/clipped/showcase/` blobs via valet tokens — no billing tier, no quota tracking, no user record. It exists purely to answer "what does Canopex actually produce?" for anonymous visitors.

The "demo" billing tier is deprecated — it overlapped with Free but was strictly worse (1 AOI, 0 retention). New unauthenticated users see the showcase; new authenticated users land on Free.

### Auth — SWA Built-in Custom Auth

Authentication uses SWA's built-in custom auth with our CIAM tenant. **There is no MSAL.js in the frontend.** SWA handles the full OAuth flow server-side.

- **Provider:** Entra External ID (CIAM) tenant `treesightauth`
- **Client ID:** `6e2abd0a-61a4-41a5-bdb5-7e1c91471fc6`
- **Login:** `/.auth/login/aad` (SWA handles redirect + callback)
- **Logout:** `/.auth/logout`
- **User info:** `/.auth/me` → JSON with `clientPrincipal`
- **API auth:** SWA injects `x-ms-client-principal` header into all `/api/*` requests
- **Session:** managed by SWA via `StaticWebAppsAuthCookie` — no client-side token management
- **Route protection:** `staticwebapp.config.json` `routes[].allowedRoles` enforced by SWA before the request reaches the managed API

The managed API reads `x-ms-client-principal` (Base64-encoded JSON) to get `userId`, `userDetails`, and `userRoles`. No PyJWT / JWKS validation is needed — SWA has already validated the token server-side.

Container Apps does not perform browser-facing auth. When the SWA managed API proxies work to Container Apps, it uses managed identity (DefaultAzureCredential) for server-to-server calls.

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

1. User authenticates via `/.auth/login/aad` (SWA handles the OAuth redirect).
2. Frontend calls `POST /api/upload/token` — SWA managed API validates `x-ms-client-principal`, mints a write-only SAS URL.
3. Frontend uploads KML/KMZ directly to blob storage via the SAS URL.
4. Event Grid emits a BlobCreated event.
5. kml_blob_trigger (Container Apps) validates event payload and starts kml_processing_orchestrator.
6. Orchestrator runs phase pipeline:
   - parse_kml
   - prepare_aoi + write_metadata
   - acquire_imagery + poll_order_suborchestrator + download_imagery + post_process_imagery
7. Metadata and imagery artifacts are written to output blob paths.
8. Frontend polls `GET /api/upload/status/{id}` via SWA managed API for progress.

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

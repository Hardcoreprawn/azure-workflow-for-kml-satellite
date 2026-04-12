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

### API Routing — BYOF (Bring Your Own Function App)

> **Architecture:** All `/api/*` calls go cross-origin from SWA to the
> Container Apps Function App. SWA serves only static files and auth.

The Container Apps Function App is the **sole API surface**. All browser API
calls go cross-origin to the FA hostname discovered from `/api-config.json`
(injected at deploy time). SWA no longer hosts any managed functions.

```text
Browser ─── /.auth/* ──→ SWA (built-in Azure AD auth)
        │
        └── /api/* ──→ Container Apps FA (all endpoints)
                          │
                          ├── reads: Cosmos DB (analysis/history, billing/status)
                          ├── writes: Blob Storage SAS minting (upload/token)
                          ├── sync: billing, catalogue, contact, health, export
                          └── async: Queue/Event Grid → Orchestrator + Activities
```

This means:

- `/api/*` routes are served by the Container Apps Function App
- SWA handles only static hosting and Azure AD auth (login/logout/me)
- Auth forwarding: frontend reads `clientPrincipal` from `/.auth/me`, base64-encodes it, and sends it as `X-MS-CLIENT-PRINCIPAL` header on cross-origin calls
- The FA `require_auth` decorator parses `X-MS-CLIENT-PRINCIPAL` to identify the user
- CORS is configured on the FA to allow requests from the SWA hostname
- Container Apps FA uses managed identity for Blob, Cosmos, Key Vault access

No unauthenticated endpoints are exposed to browsers except health and
contact-form (rate-limited). The Stripe billing webhook uses its own
signature verification.

#### Auth Forwarding (BYOF)

With BYOF, the browser makes cross-origin API calls to the Container Apps FA.
Auth works as follows:

1. User logs in via `/.auth/login/aad` (SWA built-in auth)
2. Frontend calls `/.auth/me` to get `clientPrincipal` (validated by SWA)
3. Frontend base64-encodes the raw `clientPrincipal` JSON
4. Frontend sends it as `X-MS-CLIENT-PRINCIPAL` header on each cross-origin API call
5. Container Apps FA `require_auth` decorator decodes and reads `userId`/`userRoles`

**Known limitation:** The `X-MS-CLIENT-PRINCIPAL` header is client-supplied
and not cryptographically verified by the FA. A direct HTTP client (not bound
by CORS) could forge this header. Tracked as #534 — must be fixed before
paid tiers go live. Planned approach: HMAC signature with shared secret in
Key Vault.

#### Entry Point

**Decision (2026-04-12):** The product entry point is the **Free Tier**
(authenticated, real pipeline, 5 runs/month). Demo mode (`?mode=demo`) is
deprecated and scheduled for removal (#532).

| Concept | Auth | Processing | Purpose |
|---------|------|-----------|---------|
| **Free tier** | SWA auth (authenticated) | Real — own KML/KMZ, 5 runs/month, 30-day retention | Product entry point. Sample KMLs for one-click first run. |
| **Starter / Pro / Team / Enterprise** | SWA auth (authenticated) | Real — full pipeline, higher limits, richer features | Paid plans: £19 / £49 / £149 / custom. |
| **Showcase** (deferred) | None (anonymous) | None — pre-computed static blobs | Future. Marketing for anonymous visitors. Not until pipeline is proven e2e. |

The "demo" billing tier and `?mode=demo` frontend mode have been removed.
Demo mode showed the dashboard UI without auth but couldn't run anything —
a confused middle ground that added code complexity without demonstrating
real value. The free tier with sample KMLs replaces both concepts.

Showcase (pre-computed static blobs for anonymous browsing) is a valid future
concept but is deferred until after the pipeline is verified end-to-end in
Azure (#531) and the free-tier entry point is polished (#532).

### Auth — SWA Built-in Custom Auth + BYOF Forwarding

Authentication uses SWA's built-in pre-configured Azure AD provider. SWA handles the full OAuth flow server-side with zero app registration or client secrets.

- **Provider:** SWA pre-configured Azure AD (built-in — no app registration needed)
- **Login:** `/.auth/login/aad` (SWA handles redirect + callback)
- **Logout:** `/.auth/logout`
- **User info:** `/.auth/me` → JSON with `clientPrincipal`
- **API auth:** Frontend reads `clientPrincipal` from `/.auth/me` and forwards it as `X-MS-CLIENT-PRINCIPAL` header to the Container Apps FA
- **Session:** managed by SWA via `StaticWebAppsAuthCookie` — no client-side token management
- **Route protection:** `staticwebapp.config.json` routes enforce SWA auth for protected pages; API auth is enforced by the FA `require_auth` decorator

The FA reads `X-MS-CLIENT-PRINCIPAL` (Base64-encoded JSON) to get `userId`, `userDetails`, and `userRoles`. The FA uses managed identity (DefaultAzureCredential) for all data-plane operations (Blob, Cosmos, Key Vault).

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
2. Frontend calls `POST /api/upload/token` on the Container Apps FA — `require_auth` validates `X-MS-CLIENT-PRINCIPAL`, mints a write-only SAS URL.
3. Frontend uploads KML/KMZ directly to blob storage via the SAS URL.
4. Event Grid emits a BlobCreated event.
5. kml_blob_trigger (Container Apps) validates event payload and starts kml_processing_orchestrator.
6. Orchestrator runs phase pipeline:
   - parse_kml
   - prepare_aoi + write_metadata
   - acquire_imagery + poll_order_suborchestrator + download_imagery + post_process_imagery
7. Metadata and imagery artifacts are written to output blob paths.
8. Frontend polls `GET /api/upload/status/{id}` on the Container Apps FA for progress.

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

The orchestrator calls provider adapters only through the ImageryProvider contract in `treesight/providers/base.py`.

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

Validation and defaults are implemented in `treesight/config.py`.

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

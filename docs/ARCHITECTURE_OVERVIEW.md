# Architecture Overview

Issue: #18

## Deployed Components

The production pipeline is deployed as Azure Functions on Container Apps with event-driven orchestration.

### Architecture Contract (Developer TL;DR)

Use this as the default mental model when building features:

1. Browser clients talk to one API ingress only: orchestrator hostname from `/api-config.json`.
2. Orchestrator app owns HTTP routes and Durable orchestrator entrypoints.
3. Compute app owns heavy activity execution (GDAL/raster processing) and is not a browser target.
4. Event Grid webhook target must resolve to orchestrator `blob_trigger`.
5. Route registration and auth behavior must stay symmetric across entrypoints via shared modules.

### Naming Convention

All resources are named using `{prefix}-{project_code}-{environment}` where:

- `project_code` is set in `infra/tofu/environments/{env}.tfvars` (dev: `kmlsat`)
- `environment` is set per deployment (dev: `dev`)
- Prefixes follow Azure naming standards defined in `infra/tofu/locals.tf`

| Resource | Naming Pattern | Dev Value |
| --- | --- | --- |
| Resource Group | `rg-{code}-{env}` | `rg-kmlsat-dev` |
| Function App (compute) | `func-{code}-{env}` | `func-kmlsat-dev` |
| Function App (orchestrator) | `func-{code}-{env}-orch` | `func-kmlsat-dev-orch` |
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
| **Function App (orchestrator/public API)** | `https://func-kmlsat-dev-orch.<azure-host>.azurecontainerapps.io` |
| **Function App (compute/internal worker)** | `https://func-kmlsat-dev.<azure-host>.azurecontainerapps.io` |
| **Cosmos DB** | `https://cosmos-kmlsat-dev.documents.azure.com:443/` |

The SWA hostname is Azure-assigned (no custom domain currently configured).
Both Function Apps run on Azure Container Apps in `uksouth`; SWA is in `westeurope`.

### API Routing — BYOF (Bring Your Own Function App)

> **Architecture:** All `/api/*` calls go cross-origin from SWA to the
> orchestrator Function App. SWA serves only static files. Auth is CIAM-owned.

The orchestrator Function App is the **sole public API surface**. Browser API
calls go cross-origin to the orchestrator hostname discovered from
`/api-config.json` (injected at deploy time). SWA no longer hosts managed
functions, and compute is not a browser ingress.

```text
Browser ─── MSAL.js ──→ CIAM (Entra External ID, treesightauth.ciamlogin.com)
        │                └── issues CIAM JWT
        │
        └── /api/* (Authorization: Bearer <token>) ──→ Orchestrator FA (public ingress)
              │
              ├── sync: auth/session, billing, catalogue, contact, health, export
              ├── async start/status: upload + durable orchestration API
              ├── reads/writes: Blob + Cosmos via managed identity
              └── activity fan-out ──→ Compute FA (internal worker)

SWA: static files only (no auth role in request trust chain)
```

This means:

- `/api/*` routes are served by orchestrator host only
- SWA is a static host only — no auth forwarding, no `/.auth/*` in the trust chain
- Auth: frontend acquires a CIAM JWT via MSAL.js and sends `Authorization: Bearer <token>` on every API call
- Backend `require_auth` verifies the CIAM JWT (OIDC/JWKS) and derives stable user identity from `tid:oid` claims
- CORS is configured on orchestrator host to allow requests from the SWA hostname
- Both Function Apps use managed identity for Blob, Cosmos, Key Vault access

No unauthenticated endpoints are exposed to browsers except health and
contact-form (rate-limited). The Stripe billing webhook uses its own
signature verification.

#### Auth Migration State

**Target (Option B — CIAM bearer flow):**

1. Frontend acquires CIAM JWT via MSAL.js (no SWA auth involved)
2. Frontend sends `Authorization: Bearer <token>` on every cross-origin API call
3. Orchestrator `require_auth` verifies the JWT server-side (OIDC metadata + JWKS)
4. Stable user identity derived from `tid:oid` claims (never email/upn)

**Migration status:**
- Backend bearer validation: ✅ complete (#709 closed). `AUTH_MODE=bearer_only` is ready.
- Frontend MSAL migration: 🔄 pending (#710 open). Frontend still uses `/.auth/me` transitionally.
- Deployed `AUTH_MODE`: `legacy_principal` until #710 ships and cutover is confirmed.

> **Do not add new code that depends on `X-MS-CLIENT-PRINCIPAL` forwarding or
> `/.auth/*` being in the auth trust chain.** Those are transitional and will
> be removed when #710 ships.

#### CIAM Bearer Auth (#709 — complete)

Backend bearer JWT validation is complete. `AUTH_MODE` controls the active path:

- `AUTH_MODE=legacy_principal` (currently deployed): SWA `X-MS-CLIENT-PRINCIPAL` forwarding, transitional only.
- `AUTH_MODE=dual`: bearer JWT verification active with legacy fallback.
- `AUTH_MODE=bearer_only`: CIAM bearer JWT required; no legacy path. **Target for post-#710 cutover.**

Bearer-capable modes (`dual` and `bearer_only`) require these env vars:

- `CIAM_AUTHORITY`
- `CIAM_TENANT_ID`
- `CIAM_API_AUDIENCE`
- `CIAM_JWT_LEEWAY_SECONDS` (optional, default 60)

#### Entry Point

**Decision (2026-04-12):** The product entry point is the **Free Tier**
(authenticated, real pipeline, 5 runs/month). The frontend `?mode=demo` URL
param was removed as part of issue #532 (this PR). The backend `demo` billing
tier still exists in pipeline guard logic (`tier in {"free", "demo"}`) and
will be retired separately.

| Concept | Auth | Processing | Purpose |
|---------|------|-----------|---------|
| **Free tier** | CIAM auth (authenticated) | Real — own KML/KMZ, 5 runs/month, 30-day retention | Product entry point. |
| **Starter / Pro / Team / Enterprise** | CIAM auth (authenticated) | Real — full pipeline, higher limits, richer features | Paid plans: £19 / £49 / £149 / custom. |
| **Showcase** (deferred) | None (anonymous) | None — pre-computed static blobs | Future. Marketing for anonymous visitors. Not until pipeline is proven e2e. |

The frontend `?mode=demo` entry point has been removed (#532). It showed the
dashboard UI without auth but couldn't run anything — a confused middle ground
that added complexity without demonstrating real value. The backend `demo`
billing tier remains in pipeline code and will be retired separately.

Showcase (pre-computed static blobs for anonymous browsing) is a valid future
concept but is deferred until after the pipeline is verified end-to-end in
Azure (#531) and the free-tier entry point is polished (#532).

### Auth — CIAM (Entra External ID) + MSAL Bearer Flow

Authentication uses Entra External ID (CIAM) as the identity provider. The frontend
acquires tokens via MSAL.js; the API validates them server-side. SWA is a static
host only and plays no role in the auth trust chain.

- **Provider:** Entra External ID (CIAM) — tenant `treesightauth.ciamlogin.com`
- **Frontend:** MSAL.js acquires CIAM JWT; sends `Authorization: Bearer <token>` on API calls
- **Backend:** `require_auth` decorator verifies JWT via OIDC/JWKS; identity = `tid:oid` from claims
- **SWA role:** static file host only — `/.auth/*` routes are transitional and will be removed
- **Route protection:** enforced by the FA `require_auth` / `require_auth_durable` decorators

Both Function Apps use managed identity (DefaultAzureCredential) for data-plane operations.

> **Transitional note:** Until #710 (frontend MSAL migration) ships, the deployed
> `AUTH_MODE` remains `legacy_principal` (SWA `X-MS-CLIENT-PRINCIPAL` forwarding).
> The backend is ready for `bearer_only` — the switch happens when the frontend cutover ships.

### Deploy Pipeline

```text
Push to main → CI workflow → (on success) → Deploy workflow
                                              ├─ 1. Build & push container to GHCR
                                              ├─ 2. OpenTofu plan + apply (infra/tofu/)
                                              ├─ 3. Configure compute + orchestrator Function Apps
                                              ├─ 4. Deploy Static Web App (SWA token)
                                              ├─ 5. Reconcile Event Grid subscription to orchestrator webhook
                                              └─ 6. Post-deploy smoke checks
```

Trigger: `workflow_run` on CI completion for `main`, or `workflow_dispatch`.
Concurrency: serialized per ref (no cancellation of in-progress deploys).
Config: `.github/workflows/deploy.yml`

## Data Flow

1. User authenticates via MSAL.js → CIAM issues JWT. (Transitionally: `/.auth/login/aad` via SWA until #710 ships.)
2. Frontend calls `POST /api/upload/token` on orchestrator host — `require_auth` validates the bearer JWT (or `X-MS-CLIENT-PRINCIPAL` transitionally), mints a write-only SAS URL.
3. Frontend uploads KML/KMZ directly to blob storage via the SAS URL.
4. Event Grid emits a BlobCreated event.
5. `blob_trigger` on orchestrator validates event payload and starts `treesight_orchestrator`.
6. Orchestrator runs four-phase pipeline:
   - Ingestion: parse_kml, load_offloaded_features, prepare_aoi, store_aoi_claims
   - Acquisition: load_aoi_claim, acquire_imagery/acquire_composite, poll_order, download_imagery
   - Fulfilment: post_process_imagery, submit_batch_fulfilment, poll_batch_fulfilment
   - Enrichment: run_enrichment, write_metadata, release_quota
7. Metadata and imagery artifacts are written to output blob paths.
8. Frontend polls `GET /api/upload/status/{id}` on orchestrator host for progress.

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

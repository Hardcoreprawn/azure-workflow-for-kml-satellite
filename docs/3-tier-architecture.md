# Architecture Specification: Serverless Geospatial Processing Pipeline

> **Last updated:** 2026-04-11
>
> **Status:** This document reflects the current 2-tier architecture decision.
> The original 3-tier design (SWA Functions + Durable Orchestrator + Container
> Apps Jobs) was rejected — see [Decision Record](#decision-swa-managed-functions-rejected) below.

## **1. Overview**

This system provides an event-driven, serverless pipeline for on-demand
geospatial processing. It supports large, memory-intensive workloads (KMZ/KML
parsing, imagery fulfilment, NDVI/change-detection enrichment) while
maintaining minimal idle cost.

The architecture uses **two Container Apps Function Apps** sharing a single
Durable Functions task hub:

1. **T2 — API + Orchestrator** — Always-warm BFF endpoints + lightweight
   orchestration (no GDAL/rasterio)
2. **T3 — Compute** — Scale-to-zero activity functions with full
   GDAL/rasterio/Rust stack

SWA serves **static files and auth only** — no managed functions.

---

## **2. Components**

### **2.1 Azure Static Web Apps (SWA) — Static Hosting + Auth**

**Purpose:**

- Serve the vanilla-JS frontend (`website/`)
- Handle Azure AD authentication via built-in pre-configured providers
- Route `/api/*` cross-origin to the Container Apps FA (BYOF pattern)

**Does NOT:**

- Host any managed API functions (deprecated — see decision record)
- Run any Python code
- Access Key Vault, Cosmos, or Blob directly

### **2.2 T2 — API + Orchestrator (Container Apps Function App)**

**Name:** `func-kmlsat-{env}` (Phase 1, single image) → `func-kmlsat-{env}-api` (Phase 2)

**Purpose:**

- Serve all BFF HTTP endpoints (billing, upload, status, history, export, etc.)
- Run the Durable Functions orchestrator (fan-out/fan-in)
- Run lightweight activity functions (parse, prepare, acquire, poll)

**Resources (Phase 2 target):**

- Image: ~300 MB (no GDAL, no rasterio, no Rust)
- 0.5 vCPU, 1 GiB, **min 1 replica** (always-warm BFF)
- Cost: ~£8/month

**Capabilities:**

- Managed identity (DefaultAzureCredential) for Blob, Cosmos, Key Vault
- Key Vault references for Stripe secrets
- Durable Functions v2 with `KmlSatelliteHub` task hub
- Python 3.12
- Application Insights telemetry

### **2.3 T3 — Compute (Container Apps Function App)**

**Name:** `func-kmlsat-{env}-compute` (Phase 2)

**Purpose:**

- Run CPU/RAM-intensive activity functions: download_imagery,
  post_process_imagery, run_enrichment
- Scale to zero when no pipeline work queued

**Resources:**

- Image: ~1.2 GB (GDAL + rasterio + numpy + Rust/PyO3)
- 4 vCPU, 8 GiB, **min 0 replicas** (scale-to-zero), max 10
- KEDA trigger: Durable Functions activity queue depth
- Cost: £0 idle, ~£0.40–1.60/hour during pipeline runs

**Shared with T2:**

- Same Durable Functions task hub (`KmlSatelliteHub`)
- Same storage account
- Activities auto-route via the shared work queue — no explicit dispatch needed

### **2.4 Azure Batch (Horizon)**

For AOIs ≥50k ha or future GPU workloads, Azure Batch Spot VMs provide
dedicated compute. Not currently active — deferred until proven necessary.

---

## **3. Data Flow**

### **3.1 Upload + Pipeline Trigger**

1. User authenticates via `/.auth/login/aad` (SWA built-in)
2. Frontend calls `POST /api/upload/token` → T2 mints a write-only SAS URL
3. Frontend uploads KML/KMZ directly to Blob Storage via SAS
4. Event Grid fires BlobCreated → `kml_blob_trigger` (T2)
5. Blob trigger validates input and starts the Durable orchestrator

### **3.2 Orchestration + Compute**

1. Orchestrator (T2) runs phase pipeline:
   - `parse_kml` → `prepare_aoi` → `write_metadata`
   - `acquire_imagery` → `poll_order` (sub-orchestrator)
   - `download_imagery` → `post_process_imagery` (dispatched to T3 via shared queue)
   - `run_enrichment` (T3 — NDVI, change detection, weather)
2. Results written to Blob Storage output paths
3. Status updates written to Cosmos DB

### **3.3 Status Polling**

1. Frontend polls `GET /api/upload/status/{id}` on T2
2. T2 reads from Cosmos and returns progress + results

---

## **4. Scaling Characteristics**

| Component | Replicas | Cold Start | Scale Trigger |
|-----------|----------|------------|---------------|
| SWA | N/A (CDN) | None | N/A |
| T2 (API+Orch) | 1–10 | None (min 1) | HTTP + queue depth |
| T3 (Compute) | 0–10 | ~30–60s | Activity queue depth (KEDA) |

---

## **5. Operational Boundaries**

### **T2 (API + Orchestrator)**

- Serves all BFF endpoints — auth, billing, upload, status, history, export
- Runs orchestrator and lightweight activities (parse, prepare, acquire, poll)
- Must not import GDAL, rasterio, or heavy geospatial libraries (Phase 2)
- Must not perform CPU-intensive raster processing

### **T3 (Compute)**

- Runs only activity functions that need GDAL/rasterio/Rust
- Stateless — all data via Blob Storage claim-check pattern
- Must not expose HTTP endpoints
- Must not depend on T2 availability (activities are queue-driven)

---

## **6. Error Handling & Resilience**

- Durable Functions provide automatic retries for transient failures
- Workflow state persisted in Azure Storage (durable)
- Fan-out tasks are isolated — one AOI failure doesn't block others
- Circuit breaker on Planetary Computer API (exponential backoff)
- Failed activities are retried independently by the orchestrator

---

## **7. Security Model**

- SWA handles authentication (Azure AD built-in provider)
- Auth forwarding: `X-MS-CLIENT-PRINCIPAL` header (BYOF pattern)
- Container Apps FA uses managed identity for all Azure data-plane access
- Key Vault for Stripe secrets and other sensitive config
- CORS restricted to SWA hostname
- Stripe webhooks use signature verification (not `X-MS-CLIENT-PRINCIPAL`)

---

## **8. Migration Phases**

| Phase | Topology | Baseline Cost | Status |
|-------|----------|---------------|--------|
| **Phase 1 (P3)** | Single Container Apps FA — all endpoints + pipeline | ~£20/mo | ✅ Current |
| **Phase 2 (P5)** | T2 (API+Orch) + T3 (Compute, scale-to-zero) | ~£8/mo | Planned |
| **Phase 3 (P8)** | T2 + Container Apps Jobs (per-AOI burst) | ~£8/mo + usage | Horizon |

Each phase is independently shippable and reversible.

---

## **Decision: SWA Managed Functions Rejected** {#decision-swa-managed-functions-rejected}

**Date:** 2026-04-10

The original architecture spec proposed SWA managed functions as the
always-warm API layer. This was rejected after implementation proved that SWA
managed functions:

1. **Do not support managed identity** — cannot access Key Vault, Cosmos, or
   Blob via DefaultAzureCredential (#498)
2. **Cannot resolve Key Vault references** — Stripe secrets unavailable (#506)
3. **Cannot use Durable Functions** — no orchestration capability
4. **Are pinned to Python ≤3.11** — behind the project's Python 3.12 baseline
5. **Lack Application Insights integration** — no telemetry without manual setup
6. **Duplicate every capability** — every endpoint must be re-implemented with
   restricted tooling

The Container Apps Function App already has managed identity, Key Vault,
Durable Functions, Python 3.12, and 15+ endpoints. Consolidating onto it
(BYOF pattern) eliminated ~900 lines of duplicated code and all five blockers.

**Alternatives considered:**

- **FastAPI on Container Apps** — rejected; loses Durable Functions and SWA
  auth integration
- **Azure API Management** — rejected; unnecessary cost/complexity for current scale
- **SWA linked backend** — evaluated; still requires Container Apps FA, adds
  complexity without solving managed identity gap

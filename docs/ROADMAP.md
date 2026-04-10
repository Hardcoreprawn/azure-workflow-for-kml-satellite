# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-10 (architecture topology redesign — BYOF consolidation replaces SWA managed API)

---

## Completed Milestones

| Milestone | Summary |
|-----------|---------|
| **M1 — Deployable Product** | CI/CD, Azure deployment, App Insights, cost alerts, AI Foundry, KMZ support |
| **M2 — Free Tier Launch** | Auth (SWA built-in Azure AD), onboarding, KML guide, file upload, terms/privacy, structured logging helpers |
| **M3 — Core Analysis Value** | NDVI, weather overlay, AI summaries, change detection, multi-polygon KML, enrichment split, site review fixes |
| **M4 — Revenue (12/13)** | Stripe billing, quota enforcement, pricing page, export (PDF/GeoJSON/CSV), EUDR mode, WorldCover, WDPA, circuit breaker |
| **Stage 1 — Launch Readiness** | Cosmos state migration, billing gate, user dashboard, pipeline modularisation, SSO providers, branding due diligence |
| **Stage 2 — Scaling Foundation** | Fan-out/fan-in, bulk AOI uploads, Rust acceleration, Azure Batch fallback, load testing baseline |

---

## Recently Landed

| PR | Summary |
|----|---------|
| #511 | P3 BYOF: Delete SWA managed API, route all /api/* to Container Apps FA |
| #510 | Upload BFF endpoints: upload/token + upload/status on Container Apps FA |
| #497 | Fix deploy: Key Vault purge protection one-way toggle |
| #496 | Replace CIAM with SWA pre-configured auth providers (fixes #495) |
| #490 | Code scanning alerts: URL sanitisation, mixed imports, except comments (fixes #381) |
| #487 | P2 Code Quality: orchestrator decomposition, .get() fixes, JS hardening, enrichment parallelisation |

---

## Architecture Direction

**2-tier Container Apps split** (tracking issue: #463).

SWA managed functions are deprecated — they lack managed identity, Key Vault
refs, Durable Functions, and are pinned to Python ≤3.11. All API endpoints
consolidate onto the Container Apps Function App (BYOF via `api-config.json`
hostname injection). The split is driven by **resource density**: BFF endpoints
need 0.25 vCPU always-on; compute activities need 4 vCPU occasionally.

| Phase | Topology | Baseline cost | Notes |
|-------|----------|---------------|-------|
| **Phase 1 (P3)** | Single Container Apps FA — all endpoints + pipeline | ~£20/mo (min 1 replica, 2 vCPU / 4 GiB) | Delete SWA managed API (~900 lines). One codebase. |
| **Phase 2 (P5)** | T2 (API+orchestrator) + T3 (compute, scale-to-zero) | ~£8/mo (T2 min 1 @ 0.5 vCPU) | Shared Durable task hub. T3 pays only when running. |
| **Phase 3 (P8)** | T2 + Container Apps Jobs for burst compute | ~£8/mo + ~£0.80/500-AOI run | 50 concurrent Jobs vs 10 replicas = 3× faster. |

**Scale target (500-AOI KMZ):** ~45 min wall-clock with Jobs (Phase 3) vs
~2.5 hours with replicas (Phase 2). Azure Batch stays for AOIs ≥50k ha.

### Resource demand summary

| Component | CPU | RAM | Duration |
|-----------|-----|-----|----------|
| BFF endpoints | <0.25 vCPU | <128 MiB | <100ms |
| Orchestrator | negligible | <1 MiB | coordinates only |
| Ingestion (parse + prepare) | 100–500ms burst | 10–50 MiB | <10s |
| Acquisition (STAC + polling) | minimal | <5 MiB | 10–30 min (I/O) |
| Post-process (rasterio) | **2–30s per scene** | **50–500 MiB** | 5–30s per AOI |
| Enrichment NDVI (Rust) | **500ms–2s per frame** | **500 MiB–1 GiB** | 2–5 min (8 threads) |
| Change detection (Rust) | 100–500ms per pair | 100 MiB | 30s–2 min |

Migration is phased across P3/P5/P8. Each phase is independently shippable and reversible.

---

## Priority Order

Work items are ordered by dependency and impact. Complete each group before starting the next, unless explicitly overridden.

### P0 — Live Site Fixes

Bugs visible to real users right now.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 0.1 | #438 | Fix live site: CSP violations + deploy health check regression | ✅ PR #442 (CSP + auth); #367 already resolved |
| 0.2 | #446 | Fix auth: SWA strips Authorization header → switch to built-in auth (BFF) | ✅ PR #472 |

**Exit criteria:** Auth works reliably. No CSP errors. Demo dismiss works. Telemetry flows.

**Architecture decision (2026-04-08, revised 2026-04-10):** SWA built-in
custom auth is the single auth mechanism. MSAL.js is dropped. The Container
Apps Function App is the BFF — the only API surface. SWA routes `/api/*` to
it via `api-config.json` hostname injection. SWA managed functions are
deprecated (no managed identity, no Key Vault refs, no Durable Functions,
Python ≤3.11). See `docs/ARCHITECTURE_OVERVIEW.md`.

---

### P1 — Stage 2B Completion (event-driven pipeline + BFF)

Finish the event-driven restructure. SWA becomes the sole public API surface (BFF). Parent issues: #420, #463.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2B.1 | #421 | KML/KMZ input sanitisation — zip bomb + XML validation | ✅ PR #425 |
| 2B.2 | #422 | SWA API function for SAS token minting + status polling | ✅ PR #427 |
| 2B.3 | #423 | Unify on event-driven path — remove direct orchestrator start | ✅ Merged |
| 2B.4 | #424 | Migrate read-only endpoints to SWA functions (analysis/history done) | ✅ PR #444, #481, #483, #484 |
| 2B.5 | #446 | Switch SWA auth to built-in custom auth — drop MSAL.js | ✅ PR #472 |
| 2B.6 | #464 | Add Application Insights instrumentation to SWA managed API | ✅ PR #478 |

**Exit criteria:** Upload goes via SAS URL → blob → Event Grid → orchestrator. Read-only endpoints served from Container Apps FA (formerly SWA managed functions, now consolidated). All browser API calls go through SWA `/api/*` → Container Apps FA. SWA API has full App Insights telemetry.

---

### P2 — Code Quality & Validation

Prove claims, close scanning alerts, finish simplicity fixes. Each is one PR.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| Q.1 | #452 | Decompose 338-line orchestrator into phase functions | ✅ PR #487 |
| Q.2 | #457 | Chained .get() patterns with fragile fallbacks | ✅ PR #487 |
| Q.3 | #458 | app-shell.js — fetch swallowing, innerHTML XSS, code quality | ✅ PR #487 |
| Q.4 | #459 | landing.js — missing response.ok, .then() chains, var usage | ✅ PR #487 |
| Q.5 | #437 | End-to-end validation: prove 200+ AOI KMZ processing at scale | Partial — enrichment parallelised in #487; deeper optimisation tracked in #488 |
| Q.6 | #439 | Close remaining code scanning alerts (CodeQL + Trivy IaC) | ✅ Closed |
| Q.7 | #381 | Resolve code scanning alerts: URL sanitisation, quality, encryption | ✅ PR #490 |
| Q.8 | #440 | Periodic check: libpng CVE fix in Debian bookworm | ✅ Closed — CVE fixed via apt-get upgrade |

**Exit criteria:** Orchestrator decomposed (prerequisite for #466). Scale claim proven. Code scanning clean. Simplicity violations fixed.

---

### P3 — BYOF Consolidation: Delete SWA Managed API

Consolidate all BFF endpoints onto the Container Apps Function App. Delete
the SWA managed API (~900 lines of duplicated code). SWA serves static files
only; all `/api/*` calls route to Container Apps via `api-config.json`
hostname injection.

**Why:** SWA managed functions lack managed identity (#498), Key Vault refs
(#506), Durable Functions, and are pinned to Python ≤3.11. Every capability
must be re-implemented. The Container Apps FA already has all 15+ endpoints,
managed identity, Key Vault, Python 3.12, and Durable Functions.

**BFF contract:** All endpoints use the stable camelCase API contract defined
in `docs/openapi.yaml` v2.0.0. Response shapes are decoupled from internal
Cosmos documents and blob JSON — the BFF handles all translation.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| B.1 | #498 | Root cause: SWA managed functions don't support managed identity | ✅ Superseded by BYOF |
| B.2 | #506 | Stripe Key Vault refs don't resolve in SWA managed functions | ✅ Superseded by BYOF |
| B.3 | #511 | Delete `website/api/` managed function code | ✅ PR #511 |
| B.4 | #511 | Configure `api-config.json` to route `/api/*` to Container Apps FA | ✅ PR #511 |
| B.5 | #511 | Update deploy workflow to skip SWA managed API build | ✅ PR #511 |
| B.6 | #499 | Add orchestrator status endpoint (on Container Apps) | ✅ Already exists |
| B.7 | #500 | Add timelapse-data read endpoint (on Container Apps) | ✅ Already exists |
| B.8 | #501 | Add timelapse-analysis-load endpoint (on Container Apps) | ✅ Already exists |
| B.9 | #503 | Add timelapse-analysis-save endpoint (on Container Apps) | ✅ Already exists |
| B.10 | #502 | Add timelapse-analysis compute endpoint (on Container Apps) | ✅ Already exists |
| B.11 | #504 | Add EUDR assessment endpoint (on Container Apps) | ✅ Already exists |
| B.12 | #505 | Add export endpoint — SAS redirect for large files (on Container Apps) | ✅ Already exists |

**Container Apps FA sizing (Phase 1):** 2 vCPU, 4 GiB, min 1 replica (warm
BFF), max 10 replicas (KEDA on activity queue depth). ~£20/month baseline.

**Exit criteria:** SWA managed API deleted. All `/api/*` endpoints served by
Container Apps FA. Frontend uses single camelCase shape. Auth via SWA built-in
→ `x-ms-client-principal` header forwarded to Container Apps. No #498/#506
blockers.

---

### P4 — Stage 2A: Release Safety & Promotion

Make production safe to promote into. Build once in CI, promote the same immutable artifact dev → prod.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2A.1 | #401 | Separate dev and prod deployment flows (immutable artifact promotion) | Open |
| 2A.2 | #404 | Structured JSON logging at Azure Functions startup | ✅ Closed |
| 2A.3 | #405 | Reduce Function App config drift between OpenTofu and az CLI | Open — depends #401 |
| 2A.4 | #402 | Gate production deploys on security workflow results | Open — depends #401 |
| 2A.5 | #406 | Reconcile README, runbook, and API contracts with live routes | Open — depends #401 |
| 2A.6 | #403 | Production rollout: preview users, smoke gates, promotion/demotion | Open — depends #401, #402, #405 |

**Exit criteria:** Dev/prod promotion path explicit. Preview-user rollout exists. Production deploy security-gated. Docs match code.

---

### P5 — Split T2 (API + Orchestrator) / T3 (Compute)

Split the single Container Apps FA into two apps for resource efficiency.
Both share the same Durable Functions task hub (`KmlSatelliteHub`) and
storage account. Activities auto-route via the shared work queue.

**T2 — API + Orchestrator** (`func-kmlsat-{env}-api`)

- Image: ~300 MB (no GDAL, no rasterio, no Rust)
- Functions: BFF endpoints, orchestrator, parse_kml, prepare_aoi, acquire_imagery, poll_order
- Resources: 0.5 vCPU, 1 GiB, **min 1 replica** (always-warm BFF)
- Cost: ~£8/month (mostly idle rate)

**T3 — Compute** (`func-kmlsat-{env}-compute`)

- Image: ~1.2 GB (GDAL + rasterio + Rust/PyO3)
- Functions: download_imagery, post_process_imagery, run_enrichment
- Resources: 4 vCPU, 8 GiB, **min 0** (scale-to-zero), max 10 replicas
- KEDA trigger: Durable Functions activity queue depth
- Cost: £0 idle, ~£0.40–1.60/hour during pipeline runs

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| T2.1 | #466 | Split Container Apps into API + compute images | #452, #401 |

**Exit criteria:** T2 image <300 MB (no GDAL). T3 image has full GDAL+Rust
stack. Both share Durable task hub. T2 cold-start <3s. T3 scales to zero
when no pipeline work. Baseline cost drops from ~£20 → ~£8/month.

---

### P6 — Stage 3: Growth & Retention

Features that make Canopex a habit. **Do not open Stage 3 work until P1–P5 are materially complete.**

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| 3.1 | #310 | Scheduled monitoring + change alerts | ✅ PR #394 merged |
| 3.2 | #400 | Pipeline run telemetry — log per-job stats to Cosmos | — |
| 3.3 | #399 | Pipeline ETA estimator (needs ~100 runs of telemetry data from #400) | #400 |
| 3.4 | #78 | Temporal catalogue in Cosmos DB | — |
| 3.5 | #79 | Catalogue API endpoints | #78 |
| 3.6 | #177 | H3-derived imagery/stat products | — |
| 3.7 | — | Shareable analysis links | — |

**Enrichment sources** (each is a single PR — add when approaching):

- MODIS Burned Area (`modis-64A1-061`)
- ESA CCI Land Cover (`esa-cci-lc`)
- IO LULC Annual V2 (`io-lulc-annual-v02`)
- ALOS Forest/Non-Forest (`alos-fnf-mosaic`)
- GFW deforestation alerts (GLAD + RADD)

**Exit criteria:** Users on monitoring subs. Catalogue browsable. 3+ enrichment data sources added.

---

### P7 — Stage 4: Team & API

Unlock Team tier (£149/mo) and programmatic access.

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| 4.1 | #313 | Team workspaces + tenant segregation | — |
| 4.2 | — | API documentation (interactive OpenAPI portal) | #406 |
| 4.3 | — | Webhook / Slack notifications | #310 |

**Exit criteria:** Team tier selling. API used programmatically. ARR > £30K.

---

### P8 — Stage 5: Enterprise, ML & Burst Compute (Horizon)

Advanced features, enterprise deals, competitive moats. **Do not start until Stage 4 is generating revenue.**

| Order | Issue | Title |
|-------|-------|-------|
| 5.1 | #467 | Container Apps Jobs for burst compute (Phase 3 — replaces T3 replicas with per-AOI jobs) |
| 5.2 | #82 | Tree detection model + inference pipeline |
| 5.3 | #83 | Tree health classification + temporal tracking |
| 5.4 | #84 | Annotation-driven model fine-tuning |
| 5.5 | #87 | Annotation tools and storage |
| 5.6 | #86 | Web frontend (React / Next.js) |

**Container Apps Jobs detail (#467):** Replace T3 activity replicas with
event-triggered Jobs (one per AOI). 4 vCPU / 8 GiB per Job, max 50
concurrent. Orchestrator dispatches via storage queue, polls blob for
completion. 500-AOI run: ~45 min (50 Jobs) vs ~2.5 hours (10 T3 replicas).
Azure Batch stays for AOIs ≥50k ha and future GPU workloads.

---

## Housekeeping (attach to adjacent feature work)

These are not standalone PRs — bundle with the next PR that touches the same area.

| Issue | Title | Bundle with |
|-------|-------|-------------|
| #252 | Rate limiter persistence (Redis/Cosmos) | Stage 4 multi-instance work |
| #228 | Distributed replay store for valet tokens | Stage 4 multi-instance work |
| — | Pydantic V2 request/response models | Next API surface change |
| — | Extract provider stubs from production code to test helpers | Next provider refactor |

---

## Agent Standing Orders

When working on any task:

1. **Log issues you find.** If you encounter a bug, deprecation warning, test flake, or code smell that isn't the current task, check if a GitHub issue already exists. If not, create one with the `discovered` label. Don't fix it inline — track it.
2. **Update the roadmap.** When a PR merges, update "Recently Landed" and mark the corresponding stage item as ✅.
3. **Keep context lean.** Reference issue numbers, not full descriptions. The issue holds the detail; the roadmap holds the order.

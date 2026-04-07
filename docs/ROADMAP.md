# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-07

---

## Completed Milestones

| Milestone | Summary |
|-----------|---------|
| **M1 — Deployable Product** | CI/CD, Azure deployment, App Insights, cost alerts, AI Foundry, KMZ support |
| **M2 — Free Tier Launch** | Auth (Entra CIAM), onboarding, KML guide, file upload, terms/privacy, structured logging helpers |
| **M3 — Core Analysis Value** | NDVI, weather overlay, AI summaries, change detection, multi-polygon KML, enrichment split, site review fixes |
| **M4 — Revenue (12/13)** | Stripe billing, quota enforcement, pricing page, export (PDF/GeoJSON/CSV), EUDR mode, WorldCover, WDPA, circuit breaker |
| **Stage 1 — Launch Readiness** | Cosmos state migration, billing gate, user dashboard, pipeline modularisation, SSO providers, branding due diligence |

---

## Recently Landed

| PR | Summary | Why It Matters |
|----|---------|----------------|
| #425 | KML/KMZ input sanitisation — zip bomb protection + `validate_kml_bytes()` (#421) | Slice 1 of event-driven pipeline. Hardens `maybe_unzip()` with decompression limits and adds structural XML validation. OWASP-grade input defence before the upload path moves event-driven. |
| #419 | Redesign metric alerts for scale-to-zero Container Apps (#418) | Alerting no longer fires on cold-start 503s. New Event Grid dropped-events Sev1 alert. |
| #417 | Stage 2A release safety — consolidated (#407–#412) | CIAM automation, deploy workflow hardening, docs reconciliation. |
| #394 | Scheduled monitoring + change alerts (#310) | First Stage 3 capability landed. |
| #393 | Blob storage + replay store managed identity | Runtime hardening for storage access. |

---

## In Flight

| PR | Branch | Summary |
|----|--------|--------|
| #425 | `feat/kml-input-sanitisation` | Slice 1 — input sanitisation (awaiting review) |
| #419 | `fix/scale-to-zero-alerts` | Alert redesign (awaiting review) |

**Priority call:** the event-driven pipeline restructure (#420) is the current focus. Work the slices in order (#421 → #422 → #423 → #424). Do not open more Stage 3 or Stage 4 work until the event-driven pipeline is reliably wired and Stage 2A release-safety work is materially complete.

**Infra gate before Stage 2A execution:** the live estate is still a single `dev` environment. `canopex.hrdcrprwn.com` is bound to `stapp-kmlsat-dev-site`, the checked-in deploy workflow still applies `environments/dev.tfvars` only. Before Stage 2A.1 is considered underway, prove a clean-slate `dev` recreate from OpenTofu state and make `prd` a real promotion target.

---

## Stage 1 — Launch Readiness ✅

Complete M4 and ship the product for paying users. Everything here unblocks revenue.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 1.1 | #314 | State migration to Cosmos DB | ✅ PR #350 merged |
| 1.2 | #346 | Gate billing to named users | ✅ PR #347 merged |
| 1.3 | #312 | User dashboard (history, usage) | ✅ PR #353 merged |
| 1.4 | #357 | Pipeline modularisation | ✅ PR #358 merged |
| 1.5 | #321 | SSO: Google, Microsoft, M365 Enterprise | ✅ PR #359 merged |
| 1.6 | #199 | Branding due diligence | ✅ PR #359 merged |

**Exit criteria:** Dashboard live, billing gated, SSO available, product launchable. **MET.**

---

## Stage 2 — Scaling Foundation

Handle bulk workloads (200+ AOIs). Build once, then ship product features on top.

| Order | Issue | Title | Depends On | Notes |
|-------|-------|-------|------------|-------|
| 2.1 | #320 | Load testing baseline | — | ✅ Complete |
| 2.2 | #316 | Fan-out / Fan-in + Claim Check | #314 | ✅ PR #360 merged |
| 2.3 | #311 | Bulk AOI uploads | #316 | ✅ PR #362 merged |
| 2.4 | #318 | Spike: bulk image strategy (ADR) | #316 | ✅ ADR 0002 written |
| 2.5 | #317 | Rust (PyO3) geospatial hotspots | #316 | ✅ NDVI, change detection, SCL resample accelerated |
| 2.6 | #315 | Azure Batch fallback (Spot VMs) | #316, #317 | ✅ PR #364 merged |

**Exit criteria:** 200+ concurrent AOIs process reliably without OOM or timeout.

---

## Stage 2A — Release Safety & Promotion

Make production safe to promote into. Build once in CI, promote the same immutable artifact dev -> prod, verify it live, then expose features gradually.

| Order | Issue | Title | Depends On | Notes |
|-------|-------|-------|------------|-------|
| 2A.1 | #401 | Separate dev and prod deployment flows while promoting one immutable artifact | — | Start by proving a clean-slate `dev` rebuild and explicit domain cutover path. Prod should promote the same built image/site bundle, not rebuild. |
| 2A.2 | #404 | Install structured JSON logging at Azure Functions startup | — | Make App Insights evidence and rollout telemetry trustworthy. |
| 2A.3 | #405 | Reduce Function App config drift between OpenTofu and az CLI patching | #401 | Clarify ownership of live runtime config before prod promotion becomes stricter. |
| 2A.4 | #402 | Gate production deploys on security workflow results and blocking image scan policy | #401 | Production deploy should wait for required security checks and use explicit exception paths. |
| 2A.5 | #406 | Reconcile README, runbook, and API contracts with live routes and auth behavior | #401 | Remove responder and integrator drift before rollout and smoke automation widen. |
| 2A.6 | #403 | `production_rollout`: preview users, smoke gates, and automated promotion/demotion | #401, #402, #404, #405 | Implement [PRODUCTION_ROLLOUT_SPEC.md](PRODUCTION_ROLLOUT_SPEC.md) in phases. |

**Exit criteria:** Dev/prod promotion path explicit. Deploy runs a real functional smoke after readiness. Preview-user rollout exists. Production deploy is security-gated. Docs/contracts match code. New risky features default to off and can be promoted gradually.

---

## Stage 2B — Event-Driven Pipeline Restructure

Decouple the KML upload path from the orchestrator. Make the pipeline fully event-driven so the function app can scale to zero reliably. Parent issue: #420.

| Order | Issue | Title | Depends On | Status |
|-------|-------|-------|------------|--------|
| 2B.1 | #421 | KML/KMZ input sanitisation — zip bomb + XML validation | — | ✅ PR #425 — awaiting review |
| 2B.2 | #422 | SWA API function for SAS token minting + status polling | — | 🔜 Next |
| 2B.3 | #423 | Unify on event-driven path — remove direct orchestrator start | #421, #422 | — |
| 2B.4 | #424 | Migrate read-only endpoints to SWA functions + cold start optimisation | #423 | — |

**Exit criteria:** Upload goes via SAS URL → blob → Event Grid → orchestrator. Function app has zero direct-submission paths. Read-only endpoints served from SWA managed functions (always warm).

---

## Stage 3 — Growth & Retention

Features that make Canopex a habit, not a one-off tool.

Do not open more Stage 3 work beyond what is already in flight until Stage 2A and 2B are materially complete. Growth features are safer to ship once rollout controls, post-deploy smoke, and reliable event-driven ingestion exist.

| Order | Issue | Title | Depends On | Notes |
|-------|-------|-------|------------|-------|
| 3.1 | #310 | Scheduled monitoring + change alerts | #314 | ✅ PR #394 merged. Timer Trigger (6 h) → NDVI enrichment → threshold alerts via ACS email. Cosmos `monitors` container, Pro+ tier gated. Keep subsequent risky Stage 3 features behind the rollout model from #403 rather than shipping them directly. |
| 3.2 | #78 | Temporal catalogue in Cosmos DB | #314 | Per-AOI acquisition history, date range queries |
| 3.3 | #79 | Catalogue API endpoints | #78 | `GET /api/catalogue` — paginated, filterable |
| 3.4 | — | Shareable analysis links | #312 | Viral loop: "look at this deforestation" → new visitor |
| 3.5 | — | MODIS Burned Area enrichment | — | PC `modis-64A1-061`, 500 m monthly, 2000–present |
| 3.6 | — | ESA CCI Land Cover enrichment | — | PC `esa-cci-lc`, 300 m annual, 1992–2020 |
| 3.7 | — | IO LULC Annual V2 | — | PC `io-lulc-annual-v02`, 10 m, 2017–2023 |
| 3.8 | — | ALOS Forest/Non-Forest | — | PC `alos-fnf-mosaic`, 25 m SAR-based, annual |
| 3.9 | — | GFW deforestation alerts | — | WRI GLAD + RADD alerts REST API |
| 3.10 | #177 | H3-derived imagery/stat products | — | Optional H3 analytical layer alongside AOI outputs |
| 3.11a | #400 | Pipeline run telemetry | #314 | Log per-run stats (AOI count, area, spread, enrichments, duration) to Cosmos. Start early so data accumulates. |
| 3.11b | #399 | Pipeline ETA estimator | #400 | Regression model from historical runs → predict completion time from KML/KMZ profile. Show ETA at job submission. Needs ~100 runs before activation. |

**Exit criteria:** Users on monitoring subs. Catalogue browsable. 3+ enrichment data sources added.

---

## Stage 4 — Team & API

Unlock Team tier (£149/mo) and programmatic access. Higher LTV, lower churn.

| Order | Issue | Title | Depends On | Notes |
|-------|-------|-------|------------|-------|
| 4.1 | #313 | Team workspaces + tenant segregation | #314, #312 | Shared analyses, org billing, CIAM group claims |
| 4.2 | — | API documentation (interactive) | #406 | OpenAPI and reference docs must be reconciled before building a developer portal around them |
| 4.3 | — | Webhook / Slack notifications | #310 | Enterprise integration pattern |
| 4.4 | — | Long-term historical baselines (Landsat 40-yr) | — | USGS/EE, 1985–present |
| 4.5 | — | Regional climate & land-use history | — | NOAA/ECMWF/MODIS historical context |
| 4.6 | — | ESA CCI Biomass integration | — | Self-hosted COGs (not on PC); carbon/biomass MRV |
| 4.7 | — | Security audit / pen test | — | Required before enterprise onboarding |

**Exit criteria:** Team tier selling. API used programmatically. ARR > £30K.

---

## Stage 5 — Enterprise & ML (Horizon)

Advanced features, enterprise deals, competitive moats.

| Order | Issue | Title | Notes |
|-------|-------|-------|-------|
| 5.1 | #82 | Tree detection model + inference pipeline | ML — requires training data + compute |
| 5.2 | #83 | Tree health classification + temporal tracking | Depends on #82 |
| 5.3 | #84 | Annotation-driven model fine-tuning | Depends on #82 |
| 5.4 | #87 | Annotation tools and storage | Depends on #82 |
| 5.5 | #86 | Web frontend (React / Next.js) | Major build — full SPA dashboard |
| 5.6 | — | Custom branding / white-label | Enterprise upsell |
| 5.7 | — | Super-resolution upscaling (SR4RS) | S2 10 m → ~2.5 m |
| 5.8 | — | SSO / SAML enterprise integration | CISOs require it |

---

## Housekeeping (attach to feature work)

| Issue | Title | Notes |
|-------|-------|-------|
| #252 | Rate limiter persistence | LOW — needs Redis or Cosmos; only matters at multi-instance scale |
| #228 | Distributed replay store | Valet token replay across instances; needs Redis/Table Storage |
| — | Pydantic V2 request/response models | Validation as API surface grows |
| — | Extract provider stubs to test helpers | 350+ lines of test stubs in production code |

---

## Closed Stale Issues

These were open but already shipped — all closed 2026-04-01:

| Issue | Title | Shipped In |
|-------|-------|------------|
| #75 | Per-tenant quota enforcement | PR #223 |
| #76 | Subscription tier logic | PR #299 |
| #77 | Stripe billing integration | PR #299 |
| #88 | Report export (PDF, CSV, GeoJSON) | PR #303 |

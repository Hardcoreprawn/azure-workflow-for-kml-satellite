# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-02

---

## Completed Milestones

| Milestone | Summary |
|-----------|---------|
| **M1 — Deployable Product** | CI/CD, Azure deployment, App Insights, cost alerts, AI Foundry, KMZ support |
| **M2 — Free Tier Launch** | Auth (Entra CIAM), onboarding, KML guide, file upload, terms/privacy, structured logging |
| **M3 — Core Analysis Value** | NDVI, weather overlay, AI summaries, change detection, multi-polygon KML, enrichment split, site review fixes |
| **M4 — Revenue (12/13)** | Stripe billing, quota enforcement, pricing page, export (PDF/GeoJSON/CSV), EUDR mode, WorldCover, WDPA, circuit breaker |
| **Stage 1 — Launch Readiness** | Cosmos state migration, billing gate, user dashboard, pipeline modularisation, SSO providers, branding due diligence |

---

## In Flight

*None — all PRs merged.*

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

## Stage 3 — Growth & Retention

Features that make Canopex a habit, not a one-off tool.

| Order | Issue | Title | Depends On | Notes |
|-------|-------|-------|------------|-------|
| 3.1 | #310 | Scheduled monitoring + change alerts | #314 | Timer Trigger → monthly re-run → alert on NDVI threshold breach |
| 3.2 | #78 | Temporal catalogue in Cosmos DB | #314 | Per-AOI acquisition history, date range queries |
| 3.3 | #79 | Catalogue API endpoints | #78 | `GET /api/catalogue` — paginated, filterable |
| 3.4 | — | Shareable analysis links | #312 | Viral loop: "look at this deforestation" → new visitor |
| 3.5 | — | MODIS Burned Area enrichment | — | PC `modis-64A1-061`, 500 m monthly, 2000–present |
| 3.6 | — | ESA CCI Land Cover enrichment | — | PC `esa-cci-lc`, 300 m annual, 1992–2020 |
| 3.7 | — | IO LULC Annual V2 | — | PC `io-lulc-annual-v02`, 10 m, 2017–2023 |
| 3.8 | — | ALOS Forest/Non-Forest | — | PC `alos-fnf-mosaic`, 25 m SAR-based, annual |
| 3.9 | — | GFW deforestation alerts | — | WRI GLAD + RADD alerts REST API |
| 3.10 | #177 | H3-derived imagery/stat products | — | Optional H3 analytical layer alongside AOI outputs |

**Exit criteria:** Users on monitoring subs. Catalogue browsable. 3+ enrichment data sources added.

---

## Stage 4 — Team & API

Unlock Team tier (£149/mo) and programmatic access. Higher LTV, lower churn.

| Order | Issue | Title | Depends On | Notes |
|-------|-------|-------|------------|-------|
| 4.1 | #313 | Team workspaces + tenant segregation | #314, #312 | Shared analyses, org billing, CIAM group claims |
| 4.2 | — | API documentation (interactive) | — | OpenAPI spec exists; needs dev portal + onboarding |
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

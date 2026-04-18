# Canopex — Completed Stages Archive

Archived from `docs/ROADMAP.md`. These stages are done and closed.
The roadmap retains a summary line; full detail lives here.

---

## M1 — Deployable Product

CI/CD, Azure deploy, App Insights, AI Foundry, KMZ support.

## M2 — Free Tier Launch

SWA auth, onboarding, KML guide, terms/privacy.

## M3 — Core Analysis Value

NDVI, weather, AI summaries, change detection, multi-polygon.

## M4 — Revenue

Stripe billing, quota, pricing page, export, EUDR mode,
WorldCover, WDPA.

## Stage 1 — Launch Readiness

Cosmos migration, billing gate, dashboard, SSO, branding.

## Stage 2A/2B — Scaling + Pipeline

Fan-out/fan-in, bulk AOI, Rust acceleration, Batch fallback,
BYOF consolidation.

---

## P0 — Live Site Fixes ✅

| Issue | Title | Status |
|-------|-------|--------|
| #438 | CSP violations + deploy health check regression | ✅ PR #442 |
| #446 | SWA strips Authorization header → built-in auth | ✅ PR #472 |

## P1 — Event-Driven Pipeline + BFF ✅

| Issue | Title | Status |
|-------|-------|--------|
| #421 | KML/KMZ input sanitisation | ✅ PR #425 |
| #422 | SAS token minting + status polling | ✅ PR #427 |
| #423 | Unify on event-driven path | ✅ Merged |
| #424 | Migrate read-only endpoints | ✅ PR #444, #481, #483, #484 |
| #446 | Switch to SWA built-in auth | ✅ PR #472 |
| #464 | App Insights instrumentation | ✅ PR #478 |

## P2 — Code Quality ✅

| Issue | Title | Status |
|-------|-------|--------|
| #452, #457, #458, #459 | Orchestrator decomp, code quality | ✅ PR #487 |
| #437 | E2E validation (200+ AOI) | Partial (#488) |
| #439, #381, #440 | Scanning alerts, CVEs | ✅ Closed |

## P3 — BYOF Consolidation ✅

All 12 items completed. SWA managed API deleted. All `/api/*` on
Container Apps FA via `api-config.json`.

---

## Stage 2C — Pipeline Verification & User Journey ✅

Prove the pipeline works, fix bugs, establish `/eudr/` as the entry point.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2C.1 | #531 | E2e pipeline verification in Azure | ✅ Verified 2026-04-12 |
| 2C.1 | #520 | Fix billing/status 500 | ✅ PR #536 |
| 2C.2 | #532 | Remove demo mode — Free Tier entry point | ✅ PR #546 |
| 2C.3 | #533 | EUDR pricing on pricing page | ✅ PR #615 |
| 2C.4 | #555 | Dashboard UX overhaul (6 slices) | ✅ PR #557, #559 |
| 2C.5 | #565 | Upload quota & Cosmos user management | ✅ PR #566 |
| 2C.6 | #575 | `aoi_limit` never enforced at submission | ✅ PR #620 |
| 2C.6 | #580 | Feature/AOI count mismatch (56→57) | ✅ PR #620 |
| 2C.7 | #590 | Pipeline retry model + quota refund | ✅ |
| 2C.8 | #610 | Create `/eudr/` app entry point | ✅ PR #615 |

## Stage 2F — Per-Parcel Evidence & EUDR Export ✅

| Order | Issue | Title | Status | Depends On |
|-------|-------|-------|--------|------------|
| F.0 | #583 | Data model cleanup: typed models, manifest, run timing | ✅ PR #620 | — |
| F.1 | #578 | Per-AOI enrichment: weather, NDVI, change detection | ✅ PR #620 | #583 |
| F.2 | #574 | Enrichment sub-step progress in UI | ✅ | #578 |
| F.3 | #579 | Frontend per-AOI evidence + polygon interaction | ✅ PR #620 | #578 |
| F.4 | #581 | Spatial clustering for wide-spread submissions | ✅ d01f642 | #578 |
| F.5 | #582 | EUDR per-parcel deforestation evidence export | ✅ aee1756 | #578, #579 |
| F.6 | #585 | Progressive delivery: stream per-AOI results | ✅ PR #626 | #578 |
| F.7 | #587 | Audit-grade EUDR PDF report | ✅ f586892 | #578, #582 |

## Stage 2G — EUDR Compliance Product ✅ (bar revenue)

Master tracker: #606. 21/22 issues closed. Only #613 (EUDR metered
Stripe billing) remains — tracked in Stage 2D (R.3) and 2G.5.

### 2G.1 — Data Sources ✅

| Order | Issue | Title | Dataset |
|-------|-------|-------|---------|
| D.1 | #604 | ESA WorldCover overlay | `esa-worldcover` 10m |
| D.2 | #607 | IO Annual LULC year-over-year | `io-lulc-annual-v02` 10m |
| D.3 | #608 | ALOS Forest/Non-Forest radar | `alos-fnf-mosaic` 25m |
| D.4 | #609 | Landsat historical NDVI baseline | `landsat-c2-l2` 30m |

### 2G.2 — Pipeline Logic ✅

| Order | Issue | Title |
|-------|-------|-------|
| L.1 | #600 | EUDR mode: post-2020 date filtering |
| L.2 | #601 | Coordinate-to-polygon converter (lat/lon, CSV) |
| L.3 | #603 | Deforestation-free determination per AOI |

### 2G.3 — Org & User Management ✅

| Order | Issue | Title |
|-------|-------|-------|
| ORG.1 | #614 | Org/team data model with email invites |

### 2G.4 — Frontend ✅

| Order | Issue | Title |
|-------|-------|-------|
| FE.1 | #611 | JS module decomposition (core, pipeline, evidence) |
| FE.2 | #630 | EUDR-specific UI polish on `/eudr/` |
| FE.3 | #605 | EUDR landing page + sitemap |
| FE.4 | #602 | Methodology page |

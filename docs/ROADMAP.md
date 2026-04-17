# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-17

---

## Direction

**EUDR compliance is the product.** Conservation monitoring is mothballed
until EUDR reaches revenue.

- **Landing page** (`/`) — positions Canopex as a geospatial platform,
  directs users to the EUDR app.
- **EUDR app** (`/eudr/`) — 2 free trial parcels → £49/month base +
  £3/parcel metered overage (graduated volume tiers). Billing is per-org.
- **Platform apps** (`/account/`) — shared concerns: account management,
  billing, org settings. Usable by all vertical apps.
- **Conservation** (`/app/`) — code stays, no new development or promotion.
- Master tracker: #606.

**Multi-app platform architecture:** The satellite pipeline (acquisition,
NDVI, change detection, enrichment) is shared infrastructure. Each product
vertical (EUDR, conservation, agriculture) gets its own URL namespace and
entry page. `/eudr/` ships first; others follow when EUDR reaches revenue.

**Backend:** Single Container Apps Function App — all endpoints + pipeline
in one image. 2 vCPU / 4 GiB, KEDA 1–10 replicas, ~£20/month.
T2/T3 split (#466, #467) deferred until user volume justifies it.

**Execution order:** 2C → 2D → 2E → 2F → 2G → 3 → 4 → 5.
Stages 2D and 2E can proceed in parallel.

---

## Recently Landed

| PR | Summary |
|----|---------|
| #641 | Fix enrichment 404: parse Durable Functions `input_` from JSON string (fixes #637) |
| #639 | Resolve code scanning alerts: hash-based PII redaction, dismiss base-image CVEs |
| #629 | Billing ledger, payment provider, run lifecycle, PII redaction (fixes #589) |
| #631 | EUDR UI polish: landing page, phase copy, app-shell branching (fixes #630, #632) |
| #615 | EUDR landing page, per-parcel export, audit PDF (fixes #533, #605) |
| #626 | Progressive delivery: per-AOI sub-orchestrators (fixes #585) |

---

## Completed Stages

<details>
<summary>M1–M4, Stage 1, Stage 2A/2B (expand)</summary>

| Milestone | Summary |
|-----------|---------|
| **M1 — Deployable Product** | CI/CD, Azure deploy, App Insights, AI Foundry, KMZ |
| **M2 — Free Tier Launch** | SWA auth, onboarding, KML guide, terms/privacy |
| **M3 — Core Analysis Value** | NDVI, weather, AI summaries, change detection, multi-polygon |
| **M4 — Revenue** | Stripe billing, quota, pricing page, export, EUDR mode, WorldCover, WDPA |
| **Stage 1 — Launch Readiness** | Cosmos migration, billing gate, dashboard, SSO, branding |
| **Stage 2A/2B — Scaling + Pipeline** | Fan-out/fan-in, bulk AOI, Rust accel, Batch fallback, BYOF consolidation |

### P0 — Live Site Fixes ✅

| Issue | Title | Status |
|-------|-------|--------|
| #438 | CSP violations + deploy health check regression | ✅ PR #442 |
| #446 | SWA strips Authorization header → built-in auth | ✅ PR #472 |

### P1 — Event-Driven Pipeline + BFF ✅

| Issue | Title | Status |
|-------|-------|--------|
| #421 | KML/KMZ input sanitisation | ✅ PR #425 |
| #422 | SAS token minting + status polling | ✅ PR #427 |
| #423 | Unify on event-driven path | ✅ Merged |
| #424 | Migrate read-only endpoints | ✅ PR #444, #481, #483, #484 |
| #446 | Switch to SWA built-in auth | ✅ PR #472 |
| #464 | App Insights instrumentation | ✅ PR #478 |

### P2 — Code Quality ✅

| Issue | Title | Status |
|-------|-------|--------|
| #452, #457, #458, #459 | Orchestrator decomp, code quality | ✅ PR #487 |
| #437 | E2E validation (200+ AOI) | Partial (#488) |
| #439, #381, #440 | Scanning alerts, CVEs | ✅ Closed |

### P3 — BYOF Consolidation ✅

All 12 items completed. SWA managed API deleted. All `/api/*` on
Container Apps FA via `api-config.json`.

</details>

---

## Stage 2C — Pipeline Verification & User Journey

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

**Exit:** Visitor → `/` landing page → `/eudr/` → free trial → submit
parcels → evidence → pricing. AOI limits enforced. Retries work.

---

## Stage 2D — Revenue Enablement

Auth + billing security. Prerequisites for any paid product.

| Order | Issue | Title | Status | Depends On |
|-------|-------|-------|--------|------------|
| R.0 | #553 | Enforce REQUIRE_AUTH everywhere | ✅ PR #554 | — |
| R.1 | #534 | Auth header verification (HMAC) | ✅ PR #620 | — |
| R.2 | #589 | Billing ledger, metered overage, refunds | ✅ PR #629 | — |
| R.3 | #535 | E2e Stripe billing flow on live site | Open | R.2 |
| R.4 | #406 | Reconcile docs with live routes | ✅ PR #615 | — |
| R.5 | #572 | Audit unauthenticated API endpoints | Open | — |

Approach: billing ledger is provider-agnostic (PaymentProvider protocol).
Stripe is one implementation behind the abstraction. Ledger + included/
overage logic ships first; live Stripe verification (R.3) follows.

**Exit:** Forged headers rejected. Free → paid upgrade → Stripe → quota
increase works. Overage metered. Failed runs refunded. Docs match reality.
Anonymous endpoints audited and gated or documented.

---

## Stage 2E — Release Safety & Promotion

Build once, promote dev → prod.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2E.1 | #401 | Separate dev and prod deployment flows | 🔄 In PR |
| 2E.2 | #405 | Reduce config drift (OpenTofu vs az CLI) | Open (needs #401) |
| 2E.3 | #402 | Security-gated production deploys | Open (needs #401) |
| 2E.4 | #403 | Smoke gates, promotion/demotion | Open (needs #401) |

**Exit:** Immutable artifact promotion. Security-gated. Smoke before traffic.

---

## Stage 2F — Per-Parcel Evidence & EUDR Export

Per-AOI enrichment so multi-polygon submissions produce audit-grade EUDR evidence.
**Do not start until 2C.6 bugs are fixed.**

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

**Exit:** 50-polygon submission → per-AOI NDVI/weather/change. Click polygon
→ see that AOI's results. EUDR PDF with per-parcel evidence.

---

## Stage 2G — EUDR Compliance Product ✅ (bar revenue)

Dedicated EUDR vertical on the multi-app platform. Master tracker: #606.
`/eudr/` is the entry point; shared platform concerns live at `/account/`.

**Status:** 20/22 issues closed. Pipeline, data sources, frontend, org
management, and evidence export are complete. Revenue items (#589, #613)
tracked in 2D/2G.5. Batch ops (#588) moved to Stage 4.1.

### 2G.1 — Data Sources

| Order | Issue | Title | Dataset | Depends On |
|-------|-------|-------|---------|------------|
| D.1 | #604 | ESA WorldCover overlay | `esa-worldcover` 10m | ✅ PR #620 |
| D.2 | #607 | IO Annual LULC year-over-year | `io-lulc-annual-v02` 10m | ✅ PR #620 |
| D.3 | #608 | ALOS Forest/Non-Forest radar | `alos-fnf-mosaic` 25m | ✅ PR #620 |
| D.4 | #609 | Landsat historical NDVI baseline | `landsat-c2-l2` 30m | ✅ PR #620 |
| D.5 | #612 | Landsat deep integration (2013–2016 pre-Sentinel) | `landsat-c2-l2` 30m | D.4 |

Already in pipeline: Sentinel-2 L2A, FIRMS/MODIS, WDPA, Open-Meteo.
D.4 registered the source; D.5 adds full cross-sensor NDVI computation,
QA_PIXEL cloud masking, and 7-year pre-cutoff baseline.

### 2G.2 — Pipeline Logic

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| L.1 | #600 | EUDR mode: post-2020 date filtering | ✅ PR #620 |
| L.2 | #601 | Coordinate-to-polygon converter (lat/lon, CSV) | ✅ PR #620 |
| L.3 | #603 | Deforestation-free determination per AOI | ✅ PR #620 |

### 2G.3 — Org & User Management

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| ORG.1 | #614 | Org/team data model with email invites | ✅ PR #620 |

Parcels and billing are org-scoped. Owner invites members by email;
invited users auto-join on sign-in via SWA email matching.

### 2G.4 — Frontend

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| FE.1 | #611 | JS module decomposition (core, pipeline, evidence) | ✅ PR #620 |
| FE.2 | #630 | EUDR-specific UI polish on `/eudr/` | ✅ PR #631 |
| FE.3 | #605 | EUDR landing page + sitemap | ✅ 6c3727b |
| FE.4 | #602 | Methodology page | ✅ 9f1b61e |
| FE.5 | #617 | EUDR content cluster (supplier guide, data sources, FAQ) | FE.3 |

### 2G.5 — Revenue

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| REV.1 | #613 | EUDR per-parcel metered Stripe billing | #610, #589, #614 |

**Exit:** Compliance officer uploads parcels → multi-source evidence →
deforestation-free determination → audit-grade PDF → metered billing.
All at `/eudr/`. Shared billing/account at `/account/`.

---

## Stage 3 — Growth & Retention

**Do not start until Stages 2C–2G are materially complete.**
Growth features target the EUDR vertical first. Conservation/agriculture
verticals start here as separate `/conservation/` or `/agri/` apps,
reusing the shared pipeline and platform.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 3.1 | #310 | Scheduled monitoring + change alerts | ✅ PR #394 |
| 3.2 | #400 | Pipeline run telemetry | Open |
| 3.3 | #399 | Pipeline ETA estimator | Open (needs #400) |
| 3.4 | #78 | Temporal catalogue in Cosmos DB | Open |
| 3.5 | #79 | Catalogue API endpoints | Open (needs #78) |
| 3.6 | #488 | Pipeline performance optimisation | Open |
| 3.7 | #586 | Per-user AOI imagery reuse + data retention | Open |
| 3.8 | — | Shareable analysis links | — |
| 3.9 | #618 | Brazilian authoritative data enrichment (PRODES, DETER, CAR) | Open |
| 3.10 | #619 | Evaluate Mapbox/Maxar satellite basemap | Open |

Future enrichment sources: INPE PRODES & DETER (confirmed WFS access),
CAR/SICAR property registry, MapBiomas, MODIS Burned Area, ESA CCI Land Cover,
GFW alerts.

---

## Stage 4 — Team & API

**Do not start until Stage 3 is retaining users.**

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| 4.1 | #588 | Batch operations | #578, #585, #587 |
| 4.2 | #313 | Team workspaces + tenant segregation | — |
| 4.3 | — | Interactive OpenAPI portal | — |
| 4.4 | — | Webhook / Slack notifications | — |

---

## Stage 5 — Infrastructure, Enterprise & ML (Horizon)

**Do not start until Stage 4 is generating revenue.**

| Order | Issue | Title |
|-------|-------|-------|
| 5.1 | #466 | T2/T3 Container Apps split |
| 5.2 | #467 | Container Apps Jobs for burst compute |
| 5.3 | #82 | Tree detection model + inference pipeline |
| 5.4 | #83 | Tree health classification + temporal tracking |
| 5.5 | #84 | Annotation-driven model fine-tuning |
| 5.6 | #87 | Annotation tools and storage |
| 5.7 | #86 | Web frontend (React / Next.js) |
| 5.8 | #177 | H3-derived imagery/stat products |

---

## Low Priority — Bundle with Adjacent Work

| Issue | Title | Bundle with |
|-------|-------|-------------|
| #584 | Data model internal consistency | #583 model cleanup |
| #252 | Rate limiter persistence | Stage 4 multi-instance |
| #228 | Distributed replay store | Stage 4 multi-instance |
| #573 | CSP connect-src wildcards too broad — pin hostnames | Next CSP change |
| #519 | Self-host Leaflet | Nice-to-have |
| #593 | Pydantic v2 deprecation warning (planetary-computer) | Next dependency update |
| #625 | Refactor poll_order to DF monitor pattern | Next pipeline PR |
| #550 | Upgrade GitHub Actions to Node.js 24 (deadline June 2026) | Next CI PR |
| #551 | Upgrade CodeQL Action v3 → v4 (deadline Dec 2026) | #550 CI PR |
| #569 | Verify/decommission old treesight.jablab.dev domain | Next infra PR |
| #570 | Public repo operational docs — risk acceptance | Next security review |
| #525 | Skip unchanged app settings | Next deploy PR |
| #526 | Batch tofu output calls | Next deploy PR |
| #529 | Split function app BFF + pipeline | Superseded by #466 |

---

## Agent Standing Orders

1. **Log issues you find.** Bug, deprecation, flake, code smell → check for existing issue → create with `discovered` label if none. Don't fix inline.
2. **Update the roadmap.** PR merges → update "Recently Landed" + mark stage item ✅.
3. **Keep context lean.** Reference issue numbers. The issue holds detail; the roadmap holds order.
4. **EUDR first.** Conservation is mothballed. All feature work targets EUDR (`/eudr/`). Conservation stays at `/app/`, unchanged.
5. **Multi-app platform.** Pipeline is shared; each vertical gets its own URL namespace. Shared concerns (auth, billing, org) go in `/account/` or shared modules.
6. **Pipeline foundation first.** Stage 2F (#578, #583) before 2G data sources.
7. **No infrastructure without users.** T2/T3, Container Apps Jobs, ML — deferred until volume justifies it.

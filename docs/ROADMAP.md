# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-20

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
Near-term cost work pulls forward monitoring delta/fan-out (#688) and the
orchestrator/compute split (#466). Container Apps Jobs (#467) stay deferred
until scale evidence justifies the added complexity.

**Execution order:** 2C → 2D → 2E → 2F → 2G → 3A → 3B → 3B.5 → 3C → 3 → 4 → 5.
Stages 2D and 2E can proceed in parallel. Stage 3B.5 is next priority after 3B.

---

## Recently Landed

| PR | Summary |
|----|---------|  
| #690 | feat: Stage 3B complete — imagery quality gate, provenance contract, dynamic layer picker, defensible PDF (closes #645, #649, #646, #647) |
| #667 | feat: Stage 3B.0 — Pipeline cost accumulator + resources consumed evidence card (closes #666) |
| #665 | feat: Stage 3A — EUDR assessment management: entitlement gate, CSV upload, cost estimator, flagged-parcel review (closes #660, #661, #662, #664) |
| #663 | fix: Subscribe modal hard-wall bug, EUDR entitlement gate on submit, dark theme modal styling |
| #657 | feat: Stage 2G completion — EUDR metered billing, Landsat deep integration, EUDR content cluster (closes #612, #613, #535, #617) |
| #655 | fix: Resolve code scanning alerts — repeated import, clear-text logging |
| #653 | fix: Close check_auth() HMAC bypass — endpoint auth audit (fixes #572) |
| #652 | Archive completed stages, fix stale statuses, add verification instructions (closes #538, #420) |

---

## Completed Stages

M1–M4, Stage 1, Stage 2A/2B, P0–P3, Stage 2C, Stage 2F, and
Stage 2G are complete. Completed-stage detail lives in
[docs/archive/COMPLETED_STAGES.md](archive/COMPLETED_STAGES.md); any
still-open Stage 2D/2E items remain tracked below.

---

## Stage 2D — Revenue Enablement

Auth + billing security. Prerequisites for any paid product.

| Order | Issue | Title | Status | Depends On |
|-------|-------|-------|--------|------------|
| R.0 | #553 | Enforce REQUIRE_AUTH everywhere | ✅ PR #554 | — |
| R.1 | #534 | Auth header verification (HMAC) | ✅ PR #620 | — |
| R.2 | #589 | Billing ledger, metered overage, refunds | ✅ PR #629 | — |
| R.3 | #535 | E2e Stripe billing flow on live site | 🔄 (EUDR billing PR) | R.2 |
| R.4 | #406 | Reconcile docs with live routes | ✅ PR #615 | — |
| R.5 | #572 | Audit unauthenticated API endpoints | ✅ PR #653 | — |

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
| 2E.1 | #401 | Separate dev and prod deployment flows | ✅ Closed |
| 2E.2 | #405 | Reduce config drift (OpenTofu vs az CLI) | Open |
| 2E.3 | #402 | Security-gated production deploys | Open |
| 2E.4 | #403 | Smoke gates, promotion/demotion | Open |

**Exit:** Immutable artifact promotion. Security-gated. Smoke before traffic.

---

## Stage 2G — EUDR Compliance Product ✅

Dedicated EUDR vertical on the multi-app platform. Master tracker: #606.
`/eudr/` is the entry point; shared platform concerns live at `/account/`.

**Status:** All 22 issues closed. Pipeline, core data sources, frontend,
org management, evidence export, EUDR metered billing, Landsat deep
integration, and EUDR content cluster are complete. Revenue enablement
(REV.1) merged as PR #657. Billing ledger (#589) merged as PR #629.
Batch ops (#588) moved to Stage 4.1.

### 2G.1 — Data Sources

| Order | Issue | Title | Dataset | Depends On |
|-------|-------|-------|---------|------------|
| D.1 | #604 | ESA WorldCover overlay | `esa-worldcover` 10m | ✅ PR #620 |
| D.2 | #607 | IO Annual LULC year-over-year | `io-lulc-annual-v02` 10m | ✅ PR #620 |
| D.3 | #608 | ALOS Forest/Non-Forest radar | `alos-fnf-mosaic` 25m | ✅ PR #620 |
| D.4 | #609 | Landsat historical NDVI baseline | `landsat-c2-l2` 30m | ✅ PR #620 |
| D.5 | #612 | Landsat deep integration (2013–2016 pre-Sentinel) | `landsat-c2-l2` 30m | ✅ PR #657 |

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
| FE.5 | #617 | EUDR content cluster (supplier guide, data sources, FAQ) | ✅ PR #657 |

### 2G.5 — Revenue

| Order | Issue | Title | Status | Depends On |
|-------|-------|-------|--------|------------|
| REV.1 | #613 | EUDR per-parcel metered Stripe billing | ✅ PR #657 | #610, #589, #614 |

**Exit:** Compliance officer uploads parcels → multi-source evidence →
deforestation-free determination → audit-grade PDF → metered billing.
All at `/eudr/`. Shared billing/account at `/account/`.

---

## Stage 3A — EUDR Assessment Management ✅

**Complete.** Thin vertical slices that improve how compliance
officers manage, understand, and act on their EUDR assessments.
Driven by the EUDR user journey gap analysis (`EUDR_USER_JOURNEYS.md`).

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 3A.0 | #664 | Server-side EUDR entitlement enforcement | ✅ |
| 3A.1 | #662 | CSV / coordinate paste upload in EUDR frontend | ✅ |
| 3A.2 | #661 | Cost estimator in preflight panel | ✅ |
| 3A.3 | #660 | Flagged-parcel quick-review UX in evidence panel | ✅ |

**Exit:** Server-side billing enforcement is load-bearing. Compliance
officer can paste CSV coordinates, see cost before queueing, and
understand flagged parcels without external help.

---

## Stage 3B — EUDR Evidence Quality

**Do not start until Stage 3A is complete.** Improves evidence
trustworthiness and usability for compliance officers reviewing
deforestation-free determinations.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 3B.0 | #666 | Pipeline cost accumulator + resources consumed evidence card | ✅ #667 |
| 3B.1 | #645 | Imagery quality gate: reject/deprioritise low-res for small AOIs | ✅ #690 |
| 3B.2 | #649 | Evidence provenance: traceability from viewer back to source imagery | ✅ #690 |
| 3B.3 | #646 | Imagery viewer: dynamic layer picker with smart defaults | ✅ #690 |
| 3B.4 | #647 | Defensible PDF export: embed imagery, maps, and visual evidence | ✅ #690 |

**Exit:** Compliance officer can export audit-grade PDF with embedded
evidence, trace any result back to source imagery, and review layers
interactively.

---

## Stage 3B.5 — Runtime Cost Reduction

**Do not start until Stage 3B is complete.** Small architectural work that
cuts Function wall-clock time and idle cost without changing the user-facing
product surface.

| Order  | Issue  | Title | Status |
|--------|--------|-------|--------|
| 3B.5.0 | #688 | Monitoring delta fetch + fan-out queue to cut PC wait time | ✅ In PR |
| 3B.5.1 | #466 | Split Container Apps into orchestrator + compute images | Open |

**Why now:** These are not growth features, but they directly reduce runtime
cost and cold-start overhead. `#688` bounds slow Planetary Computer waits to
new scenes only and avoids one long timer invocation processing all monitors.
`#466` lets the lightweight orchestrator stay warm cheaply while the heavy
GDAL compute image scales independently.

**Exit:** Monitoring checks fetch only deltas, queue one monitor per worker,
and the deploy architecture runs a slim orchestrator image separate from the
heavy compute image.

---

## Stage 3C — EUDR Compliance Officer UX

**Do not start until Stage 3B.5 is complete.** Closes the workflow gaps
identified in `EUDR_USER_JOURNEYS.md` for compliance officers managing
more than a handful of parcels.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 3C.0 | #673 | Supplier portfolio dashboard — all parcels, status, stats | Open |
| 3C.1 | #671 | Before/after imagery comparison view | Open |
| 3C.2 | #669 | Annotation / notes per parcel for audit trail | Open |
| 3C.3 | #672 | Human override of determination with recorded reason | Open |
| 3C.4 | #674 | Aggregated compliance summary report across multiple runs | Open |
| 3C.5 | #670 | Usage dashboard — monthly parcel consumption and billing summary | Open |

**Exit:** Compliance officer with 200+ parcels can triage by determination,
annotate flagged parcels with context, override with a recorded reason,
and export a board-ready summary report.

---

## Stage 3 — Growth & Retention

**Do not start until Stage 3C is complete.**
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
| 3.8 | #679 | Shareable analysis links — read-only permalink to a run | Open |
| 3.9 | #618 | Brazilian authoritative data enrichment (PRODES, DETER, CAR) | Open |
| 3.10 | #619 | Evaluate Mapbox/Maxar satellite basemap | Open |
| 3.11 | #437 | End-to-end validation: 200+ AOI KMZ at scale | Open |
| 3.12 | #675 | DMS and UTM coordinate format support in converter | Open |
| 3.13 | #676 | Supplier data collection template (Excel/CSV download) | Open |
| 3.14 | #678 | Country-risk auto-flagging using EU EUDR benchmarking list | Open |
| 3.15 | #677 | Commodity tracking per parcel / run for EUDR compliance | Open |
| 3.16 | #680 | GeoJSON and shapefile upload support alongside KML/KMZ | Open |

Future enrichment sources: INPE PRODES & DETER (confirmed WFS access),
CAR/SICAR property registry, MapBiomas, MODIS Burned Area, ESA CCI Land Cover,
GFW alerts.

---

## Stage 4 — Team & API

**Do not start until Stage 3 is complete.**

Execution order note: Stage 3C should also be complete before Stage 4 begins.

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| 4.1 | #588 | Batch operations | #578, #585, #587 |
| 4.2 | #313 | Team workspaces + tenant segregation | — |
| 4.3 | — | Interactive OpenAPI portal | — |
| 4.4 | — | Webhook / Slack notifications | — |
| 4.5 | #681 | Immutable audit log — tamper-evident record of all assessments | — |
| 4.6 | #682 | Per-parcel assessment history — determination timeline across runs | #673 |
| 4.7 | #685 | Role-based access control within org (viewer / analyst / admin) | — |
| 4.8 | #686 | Multi-org management for consultancy accounts | — |
| 4.9 | #684 | White-label / branded PDF reports for consultancy accounts | #686 |
| 4.10 | #683 | Annual billing option for enterprise customers | — |

---

## Stage 5 — Infrastructure, Enterprise & ML (Horizon)

**Do not start until Stage 4 is generating revenue.**

| Order | Issue | Title |
|-------|-------|-------|
| 5.1 | #466 | T2/T3 Container Apps split |
| 5.2 | #467 | Container Apps Jobs for burst compute (keep deferred until post-#466 and #437 evidence) |
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
| #463 | 3-tier architecture (SWA API / orchestrator / compute) | Superseded by #466 |
| #424 | Migrate read-only endpoints to SWA functions | Stage 5 infra split |
| #599 | EUDR competitive analysis & feature gap assessment | Next product review |

---

## Agent Standing Orders

1. **Log issues you find.** Bug, deprecation, flake, code smell → check for existing issue → create with `discovered` label if none. Don't fix inline.
2. **Update the roadmap.** PR merges → update "Recently Landed" + mark stage item ✅.
3. **Keep context lean.** Reference issue numbers. The issue holds detail; the roadmap holds order.
4. **EUDR first.** Conservation is mothballed. All feature work targets EUDR (`/eudr/`). Conservation stays at `/app/`, unchanged.
5. **Multi-app platform.** Pipeline is shared; each vertical gets its own URL namespace. Shared concerns (auth, billing, org) go in `/account/` or shared modules.
6. **Pipeline foundation first.** Stage 2F (#578, #583) before 2G data sources.
7. **No infrastructure without users.** T2/T3, Container Apps Jobs, ML — deferred until volume justifies it.

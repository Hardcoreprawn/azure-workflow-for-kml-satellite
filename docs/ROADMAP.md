# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-29

---

## Execution Order

**The stacked PR queue. Work top-to-bottom. Each row is one PR unless noted.**
Update status as work moves. Add new items at the correct priority position,
not at the bottom.

| # | Issue(s) | PR | Description | Status |
| --- | ---------- | ---- | ------------- | -------- |
| 1 | #709 | — | feat(auth): CIAM-native JWT auth in Function App (Option B phase 1) | ✅ Closed |
| 2 | #710 | #744 | feat(auth): frontend CIAM token flow with MSAL (Option B phase 2) | ✅ Closed |
| 3 | #535 | — | fix: live Stripe billing flow verification on production — Stage 2D.R3 | 🔄 Blocking revenue |
| 4 | #708 | — | fix(release): full e2e production smoke gate as promotion blocker (execution slice for #403) | Open |
| 5 | #403 | — | fix: smoke gates + promotion/demotion — Stage 2E.4 | Open |
| 6 | #400 | — | feat: pipeline run telemetry — Stage 3.2 | Open |
| 7 | #399 | — | feat: pipeline ETA estimator (needs #400) — Stage 3.3 | Open |
| 8 | #78 + #79 | — | feat: temporal catalogue in Cosmos + API (bundle) — Stage 3.4/3.5 | Open |
| 9 | #437 | — | test: E2E 200+ AOI KMZ scale validation — Stage 3.11 | Open |
| 10 | #488 | — | perf: pipeline performance optimisation — Stage 3.6 | Open |
| 11 | #675 | — | feat: DMS/UTM coordinate format support — Stage 3.12 | Open |
| 12 | #586 | — | feat: per-user AOI imagery reuse + retention — Stage 3.7 | Open |
| 13 | #679 | — | feat: shareable analysis links — Stage 3.8 | Open |
| 14 | #618 | — | feat: Brazilian data enrichment (PRODES, DETER, CAR) — Stage 3.9 | Open |
| 15 | #699 | — | research: supplier valet-token intake (may supersede #676) — Stage 3.14 | Research first |
| 16 | #676 | — | feat: supplier data collection template — Stage 3.13 | Open (post #699 research) |
| 17 | #678 | — | feat: country-risk auto-flagging — Stage 3.15 | Open |
| 18 | #677 | — | feat: commodity tracking per parcel — Stage 3.16 | Open |
| 19 | #680 | — | feat: GeoJSON/shapefile upload — Stage 3.17 | Open |
| 20 | #619 | — | eval: Mapbox/Maxar satellite basemap — Stage 3.10 | Open |

**Low-priority housekeeping** (bundle with adjacent work, don't schedule separately):
`#573` CSP wildcards · `#593` Pydantic deprecation · `#625` poll_order refactor ·
`#519` self-host Leaflet · `#569` old domain · `#570` ops docs risk · `#584` data model ·
`#525`/`#526` deploy perf · `#252`/`#228` rate limiter/replay (Stage 4) ·
`#402` security-gated production deploys (deferred in single-environment operation; keep minimal blocking scan control shipped in PR #711)

**Stage 4 starts after Stage 3 is generating revenue** — see Stage 4 section below.

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

**Backend:** Split Container Apps Function Apps — slim orchestrator ingress
and heavy compute workers. Browser clients must target orchestrator hostname
only (`/api-config.json`), while compute hosts activity-heavy execution.
Container Apps Jobs (#467) stay deferred until scale evidence justifies the
added complexity.

**Build rules (keep dev easy):**

- New browser/API features must integrate at orchestrator ingress only.
- Compute host must not be referenced by frontend config, links, or product-facing docs.
- Event Grid subscription endpoint ownership is orchestrator-only.
- Shared registration/auth modules are preferred over duplicating route wiring.
- Any deploy change touching app settings or hostnames needs a drift-guard test.

**Execution order:** 2C → 2D → 2E → 2F → 2G → 3A → 3B → 3B.5 → 3C → 3 → 4 → 5.
Stages 2D and 2E can proceed in parallel. Stage 3B.5 is next priority after 3B.

**Policy-watch gate (EUDR amendments):** Treat Parliament/Council alignment notices as directional only.
Before shipping compliance-interpretation changes, revalidate assumptions against final trilogue text,
published legal acts, and latest Commission implementation guidance.

**Value focus while rules evolve:** Prioritise low-regret capabilities that remain useful under both
strict and simplified obligations: evidence provenance, reproducible exports, audit trails, and
portfolio-level risk visibility.

---

## Recently Landed

| PR | Summary |
|----|---------|  
| #744 | feat(auth): migrate frontend from SWA `/.auth` to MSAL CIAM bearer flow (closes #710) |
| #741 | hardening: enforce function app identity contract in deploy pipeline — fail-fast identity drift check, azapi lifecycle comment overhaul, runbook invariants |
| #711 | chore: defer full #402 gating scope for single-env operation and make deploy image Trivy scan blocking (refs #402) |
| #707 | fix: Stage 2E.2 reduce OpenTofu/CLI drift — deploy-time contract verification for Function App settings/images + ownership boundary docs (closes #405) |
| #706 | chore: CI/security release-safety hardening — action pin upgrades (Trivy, CodeQL v4, Node24-compatible actions) + deploy readiness gate diagnostics/timeout hardening (closes #697, #698, #550, #551) |
| #703 | fix: enforce run ownership for timelapse save/load and return 503 on run-lookup backend failures (closes #696) |

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
| 2E.2 | #405 | Reduce config drift (OpenTofu vs az CLI) | ✅ PR #707 |
| 2E.3 | #402 | Security-gated production deploys | ⏸ Deferred (single env; partial hardening in PR #711) |
| 2E.4 | #403 | Smoke gates, promotion/demotion | Open |

**Exit:** Immutable artifact promotion. Security-gated. Smoke before traffic.

### Stage 2E.5 — Architecture Simplification Program (now)

Goal: keep runtime simple and deterministic after #466 by removing ownership
ambiguity and deploy drift.

Primary persona: ESG/EUDR compliance operator.
JTBD: submit once to one stable API surface and get reliable async completion.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2E.5.1 | #729 | single owner for Event Grid webhook target (orchestrator) | ✅ PR #736 (draft) |
| 2E.5.2 | #730 | drift guard tests: fail on compute-host Event Grid endpoint references | ✅ PR #736 (draft) |
| 2E.5.3 | #731 | symmetric rollback and readiness for compute + orchestrator apps | ✅ PR #736 (draft) |
| 2E.5.4 | #732 | shared function registration module for dual entrypoints | ✅ PR #736 (draft) |
| 2E.5.5 | #733 | orchestrator-only public API surface; compute host internalized | ✅ PR #736 (draft) |
| 2E.5.6 | #734 | post-readiness async functional smoke gate as promotion blocker | ✅ PR #736 (draft) |

Validation gates for every slice:

- `make lint`
- narrow tests first, then `make test`
- deploy-workflow slices require `workflow_dispatch` proof in dev before merge

Program done means:

1. Event Grid target ownership is singular and test-enforced.
2. Rollback logic is symmetric and verified for both apps.
3. Route registration drift between entrypoints is structurally removed.
4. Client API ingress is orchestrator-only in config, docs, and tests.
5. Promotion requires a real async transaction smoke check, not health only.

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
| 3B.5.0 | #688 | Monitoring delta fetch + fan-out queue to cut PC wait time | ✅ #691 |
| 3B.5.1 | #466 | Split Container Apps into orchestrator + compute images | ✅ #691 |

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
| 3C.0 | #673 | Supplier portfolio dashboard — all parcels, status, stats | ✅ PR #695 |
| 3C.1 | #671 | Before/after imagery comparison view | ✅ PR #695 |
| 3C.2 | #669 | Annotation / notes per parcel for audit trail | ✅ PR #695 |
| 3C.3 | #672 | Human override of determination with recorded reason | ✅ PR #695 |
| 3C.4 | #674 | Aggregated compliance summary report across multiple runs | ✅ PR #695 |
| 3C.5 | #670 | Usage dashboard — monthly parcel consumption and billing summary | ✅ PR #695 |

**Exit:** Compliance officer with 200+ parcels can triage by determination,
annotate flagged parcels with context, override with a recorded reason,
and export a board-ready summary report.

---

## Security & Housekeeping Queue

Small targeted fixes that don't belong to a product stage. Work through these
in parallel with Stage 3 or as a warm-up before each stage PR.

| Priority | Issue | Title | Status |
|----------|-------|-------|--------|
| 1 | #696 | `timelapse_analysis_save` missing run ownership check | Open — next up |
| 2 | #697 + #698 + #550 + #551 | CI: Trivy v0.70.0, Actions Node.js 24, CodeQL v4 (bundle) | Open |
| 3 | #573 | CSP connect-src wildcards too broad | Bundle with next CSP change |
| 4 | #593 | Pydantic v2 deprecation warning (planetary-computer) | Bundle with next dep update |
| 5 | #625 | Refactor poll_order to DF monitor pattern | Bundle with next pipeline PR |
| 6 | #519 | Self-host Leaflet | Nice-to-have |
| 7 | #569 | Old domain treesight.jablab.dev — verify/decommission | Bundle with next infra PR |
| 8 | #570 | Public repo operational docs — risk acceptance | Bundle with next security review |
| 9 | #584 | Data model internal consistency | Bundle with next model PR |

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
| 3.14 | #699 | Supplier parcel intake via valet-token — delegate location entry to suppliers | Open (needs research; may supersede #676) |
| 3.15 | #678 | Country-risk auto-flagging using EU EUDR benchmarking list | Open |
| 3.16 | #677 | Commodity tracking per parcel / run for EUDR compliance | Open |
| 3.17 | #680 | GeoJSON and shapefile upload support alongside KML/KMZ | Open |

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
| 5.1 | #467 | Container Apps Jobs for burst compute (defer until post-#437 scale evidence and 2E.5 simplification completion) |
| 5.2 | #82 | Tree detection model + inference pipeline |
| 5.3 | #83 | Tree health classification + temporal tracking |
| 5.4 | #84 | Annotation-driven model fine-tuning |
| 5.5 | #87 | Annotation tools and storage |
| 5.6 | #86 | Web frontend (React / Next.js) |
| 5.7 | #177 | H3-derived imagery/stat products |

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
8. **Revalidate legal assumptions.** Before merging EUDR rule-interpretation changes, verify against current final legal text and Commission guidance; if assumptions changed, log a focused issue and update roadmap ordering.

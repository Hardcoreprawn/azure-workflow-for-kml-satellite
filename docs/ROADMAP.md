# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-12 (UX review + auth hardening)

---

## Architecture Decision: Entry Point

**Decision (2026-04-12):** The product entry point is the **Free Tier** (authenticated, real pipeline, 5 runs). The landing page directs users to sign in and run a real analysis.

- **Free tier** = authenticated, 5 real analyses/month, sample KMLs for one-click first run
- **Showcase** = deferred. Pre-computed static samples for anonymous visitors are a nice-to-have after the real pipeline is proven end-to-end. Not current priority.
- **Demo mode** = removed (PR #546, issue #532). Frontend `?mode=demo` deleted. Backend `demo` billing tier remains in pipeline guards, to be retired separately.

See `docs/ARCHITECTURE_OVERVIEW.md` § "Entry Point" for details.

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
| #554 | Enforce REQUIRE_AUTH in all deployed environments (fixes #553) |
| #549 | Fix deploy: declarative import block for custom domain |
| #546 | Remove frontend demo mode (`?mode=demo`), unify on Free Tier entry (closes #532) |
| #545 | CORS fix: set custom_domain in dev.tfvars for apex domain |
| #543 | Fix deploy: merge scaling PATCHes into single call to avoid 409 Conflict |
| #540 | Cosmos-only storage: remove cosmos_or_blob dual-write, fix RLock deadlock, fix exception cache poisoning |

---

## Architecture Direction

**Single Container Apps FA** — all endpoints + pipeline in one image.

SWA managed functions are deleted. All API endpoints are on the Container
Apps Function App (BYOF via `api-config.json` hostname injection). SWA
serves static files and auth only.

**Current topology (Phase 1):** Single Container Apps FA — 2 vCPU / 4 GiB,
min 1 replica (warm BFF), max 10 replicas (KEDA). ~£20/month baseline.

**Future split (deferred until user volume justifies it):**

| Phase | Topology | Baseline cost | Status |
|-------|----------|---------------|--------|
| **Phase 1** (current) | Single FA | ~£20/mo | ✅ Active |
| **Phase 2** (#466) | T2 API + T3 Compute (scale-to-zero) | ~£8/mo | Deferred |
| **Phase 3** (#467) | T2 + Container Apps Jobs | ~£8/mo + burst | Deferred |

The T2/T3 split saves ~£12/month. Do not start until user count justifies
the engineering effort.

---

## Priority Order

Priorities are restructured per the 2026-04-12 project review. The core
finding: **the pipeline works, the architecture is sound, but the user
journey is broken.** All new work prioritises the path from "visitor lands"
to "user pays and gets value."

Complete each group before starting the next.

---

## Completed Stages (legacy P0–P3 numbering)

<details>
<summary>Expand completed stages</summary>

### P0 — Live Site Fixes ✅

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 0.1 | #438 | Fix live site: CSP violations + deploy health check regression | ✅ PR #442 |
| 0.2 | #446 | Fix auth: SWA strips Authorization header → switch to built-in auth | ✅ PR #472 |

### P1 — Stage 2B: Event-Driven Pipeline + BFF ✅

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2B.1 | #421 | KML/KMZ input sanitisation — zip bomb + XML validation | ✅ PR #425 |
| 2B.2 | #422 | SAS token minting + status polling | ✅ PR #427 |
| 2B.3 | #423 | Unify on event-driven path | ✅ Merged |
| 2B.4 | #424 | Migrate read-only endpoints | ✅ PR #444, #481, #483, #484 |
| 2B.5 | #446 | Switch to SWA built-in auth | ✅ PR #472 |
| 2B.6 | #464 | App Insights instrumentation | ✅ PR #478 |

### P2 — Code Quality & Validation ✅

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| Q.1–Q.4 | #452, #457, #458, #459 | Orchestrator decomp, code quality | ✅ PR #487 |
| Q.5 | #437 | E2E validation (200+ AOI) | Partial (#488 tracks deeper work) |
| Q.6–Q.8 | #439, #381, #440 | Scanning alerts, CVEs | ✅ Closed |

### P3 — BYOF Consolidation ✅

All 12 items completed. SWA managed API deleted. All `/api/*` endpoints on
Container Apps FA. Frontend uses BYOF routing via `api-config.json`.

</details>

---

### Stage 2C — Pipeline Verification & User Journey (NOW)

**This is the current focus.** Prove the pipeline works end-to-end in Azure,
fix the bugs that break the signed-in experience, and make the product
entry point unambiguous.

#### 2C.1 — Pipeline End-to-End Verification

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| E.1 | #531 | Verify e2e pipeline in Azure: sign in → upload KML → results | ✅ Verified 2026-04-12 |
| E.2 | #520 | Fix `/api/billing/status` returns 500 for signed-in users | ✅ PR #536 |

**Exit criteria:** ✅ A user can sign in on the live SWA URL, upload a sample
KML, and see a completed analysis with imagery, NDVI, weather, and AI
narrative. Billing/status returns 200. Pipeline verified end-to-end on
2026-04-12 (1 feature, 5 Sentinel-2 images acquired, clipped, enriched
in 42s).

#### 2C.2 — Unify Entry Point (Kill Demo Mode)

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| U.1 | #532 | Remove demo mode — unify on Free Tier with sample KMLs | ✅ PR #546 |

The entry point is the Free Tier (5 runs, authenticated, real pipeline).
Demo mode (`?mode=demo`) is removed. Landing page says "Start Free" →
sign in → sample KML picker → one-click first run.

**Exit criteria:** No `?mode=demo` handling in frontend. Unauthenticated
`/app/` shows sign-in gate with free-tier messaging. First-run flow offers
sample KMLs. All demo-specific code removed.

#### 2C.3 — Pricing Clarity

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| P.1 | #533 | Show real prices on pricing page | Open |

**Exit criteria:** Pricing cards show £0/£19/£49/£149 with clear limits.
"Express Interest" replaced with actionable subscribe buttons for
Starter/Pro. Enterprise remains "Contact Us."

**Stage 2C exit criteria:** The minimum viable user journey works. A visitor
can: see what Canopex does (landing page) → sign in (free) → run analysis
(sample KML) → see results → understand upgrade path (real prices).

#### 2C.4 — Dashboard UX Overhaul

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| UX.1 | #555 | Reorder layout: submission above evidence | Open |
| UX.2 | #555 | Replace jargon with user language | Open |
| UX.3 | #555 | Collapse first-load noise for new users | Open |
| UX.4 | #555 | Auto-scroll to results on completion | Open |
| UX.5 | #555 | Streamline submission form | Open |
| UX.6 | #555 | Deduplicate export buttons | Open |

See `docs/UX_REVIEW_2026-04-12.md` for full findings and implementation
plan. All slices are frontend-only. Recommended order: 1 → 2 → 3 → 4 → 5 → 6.

**Exit criteria:** File upload is visible without scrolling. Results auto-
scroll on completion. Zero "signed-in" / "workspace lens" / "durable" jargon
in user-facing strings. First-load elements <12 (currently ~25).

---

### Stage 2D — Revenue Enablement (This Month)

Security and billing verification required before accepting real payments.

| Order | Issue | Title | Status | Depends On |
|-------|-------|-------|--------|------------|
| R.0 | #553 | Enforce REQUIRE_AUTH in all deployed environments | ✅ PR #554 | — |
| R.1 | #534 | Auth header verification: prevent X-MS-CLIENT-PRINCIPAL forgery | Open | — |
| R.2 | #535 | Verify end-to-end Stripe billing flow on live site | Open | #520 |
| R.3 | #406 | Reconcile README, runbook, and API contracts with live routes | Open | — |

**Exit criteria:** Auth is cryptographically verified (forged headers
rejected). Free → Starter upgrade → Stripe payment → quota increase → run
analysis works end-to-end. API docs match live behavior.

---

### Stage 2E — Release Safety & Promotion

Build once in CI, promote the same immutable artifact dev → prod.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2A.1 | #401 | Separate dev and prod deployment flows | 🔄 In PR |
| 2A.2 | #405 | Reduce config drift between OpenTofu and az CLI | Open — depends #401 |
| 2A.3 | #402 | Gate production deploys on security workflow results | Open — depends #401 |
| 2A.4 | #403 | Production rollout: smoke gates, promotion/demotion | Open — depends #401 |

**Exit criteria:** Dev/prod promotion path explicit. Production deploy
security-gated. Smoke checks pass before traffic shift.

---

### Stage 3 — Growth & Retention

Features that make Canopex a habit. **Do not start until Stage 2C–2E are
materially complete.**

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 3.1 | #310 | Scheduled monitoring + change alerts | ✅ PR #394 |
| 3.2 | #400 | Pipeline run telemetry — per-job stats | Open |
| 3.3 | #399 | Pipeline ETA estimator | Open (needs #400) |
| 3.4 | #78 | Temporal catalogue in Cosmos DB | Open |
| 3.5 | #79 | Catalogue API endpoints | Open (needs #78) |
| 3.6 | #488 | Pipeline performance optimisation | Open |
| 3.7 | — | Shareable analysis links | — |

**Enrichment sources** (add when a user requests them):

- MODIS Burned Area, ESA CCI Land Cover, IO LULC, ALOS Forest, GFW alerts

**Exit criteria:** Users on monitoring subs. Catalogue browsable.

---

### Stage 4 — Team & API

Unlock Team tier (£149/mo) and programmatic access. **Do not start until
Stage 3 features are retaining users.**

| Order | Issue | Title |
|-------|-------|-------|
| 4.1 | #313 | Team workspaces + tenant segregation |
| 4.2 | — | Interactive OpenAPI portal |
| 4.3 | — | Webhook / Slack notifications |

---

### Stage 5 — Infrastructure Optimisation, Enterprise & ML (Horizon)

**Do not start until Stage 4 is generating revenue.** These are post-revenue
features and cost optimisations.

| Order | Issue | Title |
|-------|-------|-------|
| 5.1 | #466 | Split Container Apps into API + compute images (T2/T3) |
| 5.2 | #467 | Container Apps Jobs for burst compute |
| 5.3 | #82 | Tree detection model + inference pipeline |
| 5.4 | #83 | Tree health classification + temporal tracking |
| 5.5 | #84 | Annotation-driven model fine-tuning |
| 5.6 | #87 | Annotation tools and storage |
| 5.7 | #86 | Web frontend (React / Next.js) |
| 5.8 | #177 | H3-derived imagery/stat products |

---

## Issue Triage (2026-04-12)

Per the project review, open issues are triaged as follows:

### Active — Do Now (Stage 2C)

| # | Title | Priority |
|---|-------|----------|
| #531 | Pipeline e2e verification in Azure | ✅ Verified |
| #520 | billing/status 500 | ✅ PR #536 |
| #532 | Remove demo mode — Free Tier entry point | ✅ PR #546 |
| #555 | Dashboard UX overhaul (6 slices) | P0 |
| #533 | Real prices on pricing page | P1 |

### Active — This Month (Stage 2D)

| # | Title |
|---|-------|
| #553 | Enforce REQUIRE_AUTH in all environments |
| #534 | Auth header verification (HMAC) |
| #535 | E2e Stripe billing flow |
| #406 | Reconcile docs with live routes |

### Active — Release Safety (Stage 2E)

| # | Title |
|---|-------|
| #401 | Dev/prod deploy flows |
| #405 | Config drift reduction |
| #402 | Security-gated deploys |
| #403 | Production rollout gates |

### Deferred — Post-Revenue

| # | Title | When |
|---|-------|------|
| #466 | T2/T3 split | When cost exceeds revenue |
| #467 | Container Apps Jobs | After T2/T3 split |
| #313 | Team workspaces | When Team tier has customers |
| #82, #83, #84 | Tree detection / health / ML | Stage 5 |
| #86 | React frontend | Stage 5 |
| #87 | Annotation tools | Stage 5 |

### Closed (2026-04-12)

| # | Title | Reason |
|---|-------|--------|
| #474 | Migrate remaining browser-facing endpoints to SWA | Superseded by BYOF |

### Low Priority / Bundle with Adjacent Work

| # | Title | Bundle with |
|---|-------|-------------|
| #252 | Rate limiter persistence | Stage 4 multi-instance |
| #228 | Distributed replay store | Stage 4 multi-instance |
| #488 | Pipeline perf optimisation | Stage 3 |
| #513 | Infracost usage metric name | Next infra PR |
| #517 | CSP img-src unused CartoDB | Next CSP change |
| #518 | CSP connect-src missing unpkg | Next CSP change |
| #519 | Self-host Leaflet | Nice-to-have |
| #525 | Skip unchanged app settings | Next deploy PR |
| #526 | Batch tofu output calls | Next deploy PR |
| #527 | CSP blocks Leaflet source map | Next CSP change |
| #528, #529 | Duplicate split FA issues | Superseded by #466 |

---

## Housekeeping (attach to adjacent feature work)

| Issue | Title | Bundle with |
|-------|-------|-------------|
| #252 | Rate limiter persistence (Redis/Cosmos) | Stage 4 multi-instance work |
| #228 | Distributed replay store for valet tokens | Stage 4 multi-instance work |

---

## Agent Standing Orders

When working on any task:

1. **Log issues you find.** If you encounter a bug, deprecation warning, test flake, or code smell that isn't the current task, check if a GitHub issue already exists. If not, create one with the `discovered` label. Don't fix it inline — track it.
2. **Update the roadmap.** When a PR merges, update "Recently Landed" and mark the corresponding stage item as ✅.
3. **Keep context lean.** Reference issue numbers, not full descriptions. The issue holds the detail; the roadmap holds the order.
4. **User journey first.** Do not open Stage 3+ work while the minimum viable user journey (Stage 2C) is incomplete.
5. **No infrastructure without users.** T2/T3 split, Container Apps Jobs, and ML work are deferred until user volume or revenue justifies them.

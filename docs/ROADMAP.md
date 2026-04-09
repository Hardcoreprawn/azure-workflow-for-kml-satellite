# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. This list holds the order.

Last updated: 2026-04-09 (PR #487 merged — P2 Q.1–Q.4 + enrichment parallelisation)

---

## Completed Milestones

| Milestone | Summary |
|-----------|---------|
| **M1 — Deployable Product** | CI/CD, Azure deployment, App Insights, cost alerts, AI Foundry, KMZ support |
| **M2 — Free Tier Launch** | Auth (Entra CIAM), onboarding, KML guide, file upload, terms/privacy, structured logging helpers |
| **M3 — Core Analysis Value** | NDVI, weather overlay, AI summaries, change detection, multi-polygon KML, enrichment split, site review fixes |
| **M4 — Revenue (12/13)** | Stripe billing, quota enforcement, pricing page, export (PDF/GeoJSON/CSV), EUDR mode, WorldCover, WDPA, circuit breaker |
| **Stage 1 — Launch Readiness** | Cosmos state migration, billing gate, user dashboard, pipeline modularisation, SSO providers, branding due diligence |
| **Stage 2 — Scaling Foundation** | Fan-out/fan-in, bulk AOI uploads, Rust acceleration, Azure Batch fallback, load testing baseline |

---

## Recently Landed

| PR | Summary |
|----|---------|
| #487 | P2 Code Quality: orchestrator decomposition, .get() fixes, JS hardening, enrichment parallelisation |
| #484 | SWA catalogue endpoints — list, detail, by_run, by_aoi (completes #465 / T1.1) |
| #483 | SWA contact form, readiness, contract endpoints + deploy smoke-check fix (partial #465) |
| #481 | SWA billing endpoints — billing/status, billing/checkout, billing/portal (partial #465, #474) |
| #478 | SWA API App Insights instrumentation — connection string, OTEL service name, sampling (fixes #464) |
| #477 | SWA auth fix: use CIAM_CLIENT_ID/SECRET instead of managed-identity refs |

---

## Architecture Direction

**3-tier serverless split** (tracking issue: #463, spec: `docs/3-tier-architecture.md`).

| Tier | Runtime | Python | Purpose |
|------|---------|--------|---------|
| **T1 — SWA Functions** | SWA managed API | 3.11 | Always-warm: auth, reads, status, SAS minting |
| **T2 — Orchestrator** | Container Apps (Functions) | 3.12 | Scale-to-zero: Durable orchestration, triggers |
| **T3 — Compute** | Container Apps (Activities → Jobs) | 3.12+ | Scale-to-zero: GDAL, rasterio, Rust/PyO3 |

Migration is phased across P1/P3/P5/P8 below. Each phase is independently shippable.

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

**Architecture decision (2026-04-08):** SWA built-in custom auth is the single auth mechanism. MSAL.js is dropped. The SWA managed API is the BFF — the only public API surface. Container Apps receives work only via Event Grid/queue, never directly from the browser for auth-gated operations. See `docs/ARCHITECTURE_OVERVIEW.md`.

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

**Exit criteria:** Upload goes via SAS URL → blob → Event Grid → orchestrator. Read-only endpoints served from SWA managed functions. All browser API calls go through SWA `/api/*` — Container Apps never directly serves auth-gated browser requests. SWA API has full App Insights telemetry.

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
| Q.7 | #381 | Resolve code scanning alerts: URL sanitisation, quality, encryption | Open |
| Q.8 | #440 | Periodic check: libpng CVE fix in Debian bookworm | Open |

**Exit criteria:** Orchestrator decomposed (prerequisite for #466). Scale claim proven. Code scanning clean. Simplicity violations fixed.

---

### P3 — 3-Tier Phase 1: SWA as Primary API (T1)

Expand SWA managed API to serve all user-facing reads. Part of #463.

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| T1.1 | #465 | Move health, billing/status, catalogue, contact to SWA | ✅ PR #481 (billing), #483 (contact, readiness, contract), #484 (catalogue) |
| T1.2 | #424 | Complete remaining SWA endpoint migration | #465 |

**Exit criteria:** SWA serves all read + lightweight write endpoints. Container App only wakes for pipeline execution and write paths. No GDAL in SWA image.

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

### P5 — 3-Tier Phase 2: Split Orchestrator + Compute (T2/T3)

Separate the Container Apps function app into two images. Part of #463.

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| T2.1 | #466 | Split Container Apps into orchestrator + compute images | #452, #401, #465 |

**Exit criteria:** Orchestrator image &lt;300 MB (no GDAL). Compute image has full stack. Both share Durable task hub. Cold-start &lt;3s for orchestrator.

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
| 5.1 | #467 | Container Apps Jobs for burst compute (3-tier Phase 3) |
| 5.2 | #82 | Tree detection model + inference pipeline |
| 5.3 | #83 | Tree health classification + temporal tracking |
| 5.4 | #84 | Annotation-driven model fine-tuning |
| 5.5 | #87 | Annotation tools and storage |
| 5.6 | #86 | Web frontend (React / Next.js) |

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

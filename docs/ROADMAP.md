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
| **Stage 2 — Scaling Foundation** | Fan-out/fan-in, bulk AOI uploads, Rust acceleration, Azure Batch fallback, load testing baseline |

---

## Recently Landed

| PR | Summary |
|----|---------|
| #435 | Auth retry on 401 + web test cost reduction |
| #436 | Infracost CI cost gate with live Azure usage metrics |
| #427 | SWA managed API functions — SAS token minting + status polling (#422) |
| #425 | KML/KMZ input sanitisation — zip bomb protection + `validate_kml_bytes()` (#421) |
| #426 | Docs, tooling, roadmap update |
| #419 | Redesign metric alerts for scale-to-zero Container Apps (#418) |

---

## Priority Order

Work items are ordered by dependency and impact. Complete each group before starting the next, unless explicitly overridden.

### P0 — Live Site Fixes (do first)

Bugs visible to real users right now.

| Order | Issue | Title | PR-sized? |
|-------|-------|-------|-----------|
| 0.1 | #438 | Fix live site: CSP violations + deploy health check regression | Single PR — bundles #367, #408, #409 |

**Exit criteria:** Deploy succeeds. No CSP console errors. Demo dismiss works. Azure Monitor telemetry flows.

---

### P1 — Stage 2B Completion (event-driven pipeline)

Finish the event-driven restructure. Parent issue: #420.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2B.1 | #421 | KML/KMZ input sanitisation — zip bomb + XML validation | ✅ PR #425 |
| 2B.2 | #422 | SWA API function for SAS token minting + status polling | ✅ PR #427 |
| 2B.3 | #423 | Unify on event-driven path — remove direct orchestrator start | ✅ Merged |
| 2B.4 | #424 | Migrate read-only endpoints to SWA functions + cold start optimisation | 🔜 Next |

**Exit criteria:** Upload goes via SAS URL → blob → Event Grid → orchestrator. Function app has zero direct-submission paths. Read-only endpoints served from SWA managed functions (always warm).

---

### P2 — Validation & Tech Debt

Prove claims, close scanning alerts, clean up code quality debt. Each is one PR.

| Order | Issue | Title | PR-sized? |
|-------|-------|-------|-----------|
| V.1 | #437 | End-to-end validation: prove 200+ AOI KMZ processing at scale | Single PR — test + baseline docs |
| V.2 | #439 | Close remaining code scanning alerts (CodeQL false positives + Trivy IaC) | Single PR — suppress/fix 7 alerts |
| V.3 | #381 | Resolve code scanning alerts: URL sanitisation, quality, encryption | Single PR — partial fix batch |
| V.4 | #440 | Periodic check: libpng CVE fix in Debian bookworm | Single PR if fix landed; close if not |

**Exit criteria:** Scale claim has evidence. Code scanning dashboard shows zero open (or explicitly suppressed with rationale).

---

### P3 — Stage 2A: Release Safety & Promotion

Make production safe to promote into. Build once in CI, promote the same immutable artifact dev → prod, verify it live.

| Order | Issue | Title | Status |
|-------|-------|-------|--------|
| 2A.1 | #401 | Separate dev and prod deployment flows (immutable artifact promotion) | Open |
| 2A.2 | #404 | Structured JSON logging at Azure Functions startup | ✅ Closed |
| 2A.3 | #405 | Reduce Function App config drift between OpenTofu and az CLI | Open — depends #401 |
| 2A.4 | #402 | Gate production deploys on security workflow results | Open — depends #401 |
| 2A.5 | #406 | Reconcile README, runbook, and API contracts with live routes | Open — depends #401 |
| 2A.6 | #403 | Production rollout: preview users, smoke gates, promotion/demotion | Open — depends #401, #402, #405 |

**Exit criteria:** Dev/prod promotion path explicit. Deploy runs functional smoke after readiness. Preview-user rollout exists. Production deploy is security-gated. Docs/contracts match code.

---

### P4 — Stage 3: Growth & Retention

Features that make Canopex a habit. **Do not open Stage 3 work until P1–P3 are materially complete.**

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

### P5 — Stage 4: Team & API

Unlock Team tier (£149/mo) and programmatic access.

| Order | Issue | Title | Depends On |
|-------|-------|-------|------------|
| 4.1 | #313 | Team workspaces + tenant segregation | — |
| 4.2 | — | API documentation (interactive OpenAPI portal) | #406 |
| 4.3 | — | Webhook / Slack notifications | #310 |

**Exit criteria:** Team tier selling. API used programmatically. ARR > £30K.

---

### P6 — Stage 5: Enterprise & ML (Horizon)

Advanced features, enterprise deals, competitive moats. **Do not start until Stage 4 is generating revenue.**

| Order | Issue | Title |
|-------|-------|-------|
| 5.1 | #82 | Tree detection model + inference pipeline |
| 5.2 | #83 | Tree health classification + temporal tracking |
| 5.3 | #84 | Annotation-driven model fine-tuning |
| 5.4 | #87 | Annotation tools and storage |
| 5.5 | #86 | Web frontend (React / Next.js) |

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

# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. The project board holds the live queue.

Last updated: 2026-06-13

---

## Active Work Queue

**Live prioritised board:** [github.com/users/Hardcoreprawn/projects/2](https://github.com/users/Hardcoreprawn/projects/2/views/1)

Use the board for day-to-day prioritisation. Issues are labelled:

- `priority:now` — currently being worked on
- `priority:next` — up next after current work
- `priority:backlog` — ordered, not yet scheduled

**Housekeeping** (bundle with adjacent work, don't schedule separately):
`#573` CSP wildcards · `#593` Pydantic deprecation · `#625` poll_order refactor ·
`#519` self-host Leaflet · `#569` old domain · `#570` ops docs risk · `#584` data model ·
`#525`/`#526` deploy perf · `#252`/`#228` rate limiter/replay (Stage 4) ·
`#402` security-gated production deploys (deferred; partial hardening in PR #711)

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
Container Apps Jobs (#467) stay deferred — confirmed by cost analysis (2026-05):
both FAs are on the Consumption plan with alwaysReady=0, so idle cost is already
£0. CAJ would add complexity without reducing cost. Revisit when sustained user
load makes the per-invocation billing model a disadvantage vs a dedicated worker.

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
| —  | **Recovery confirmed (#894):** `origin/feat/landsat-deep-integration` examined — the single unique feature commit (Landsat deep integration, #612) was already incorporated into main via PR #657. All 25 `test_landsat_deep.py` tests pass. Branch can be retired. |
| #874 | fix(pipeline): parallelise per-AOI enrichment loop ([#863](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/863)) — prevent activity timeout at 50+ AOIs with ThreadPoolExecutor fan-out, capped concurrency, per-AOI failure isolation, and ordering-preservation tests. |
| #873 | chore: board-based prioritisation + pipeline regression guards — ROADMAP.md + copilot-instructions updated to use GitHub Project board for day-to-day ordering; `store_claims_batch` treats empty `feature_name` same as `None` (index-based fallback key); `_build_order_lookups` skips orders with no `order_id`; new edge-case tests in `test_geo.py`, `test_ingestion.py`, `test_pipeline.py`; duplicate-name KML fixture added. |
| —  | **MILESTONE (2026-05-20): First confirmed end-to-end pipeline run in production.** KML upload → blob trigger → orchestrator → imagery acquisition → NDVI + change detection + climate enrichment → results rendered in dashboard. Mean NDVI, range, trajectory, 54-frame timelapse, and EUDR compliance entry point all returned correctly. Stage 2C proof-of-life confirmed. |
| #856 | chore(deps): bump idna 3.11→3.15 — fixes CVE-2024-3651 (IDNA label length bypass, possible ReDoS via crafted hostname). `uv lock --upgrade-package idna`. All 1826 tests pass. |
| #855 | feat(ci): auth-free pipeline smoke test in deploy workflow — `scripts/pipeline_smoke.py` injects KML + demo ticket directly into blob storage (stdlib+az CLI only; storage key via ARM Contributor, no Blob Data RBAC needed); Event Grid fires `blob_trigger` naturally; polls Durable management API to assert `runtimeStatus==Completed`. Gated `DEPLOY_ENV != prd`. Regression lock in `test_launch_readiness.py`. |
| #853 | fix(parse): GDAL/PROJ parse hang — `PROJ_NETWORK=OFF` + `GDAL_HTTP_TIMEOUT=30` + `GDAL_MAX_HTTP_RETRY=0` + `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` set at module load before GDAL initialises; 60s `ThreadPoolExecutor` timeout with `shutdown(wait=False)` so a stuck GDAL thread never blocks teardown. Fixes #852. |

---

## Stage status

- **Stage 2C (Pipeline Verification & User Journey):** Complete
- **Stage 2D (Revenue Enablement):** Complete
- **Stage 2E (Release Safety):** Complete
- **Stage 3 (Growth & Retention):** In Progress

---

## Per-stage issue tables

See the [live board](https://github.com/users/Hardcoreprawn/projects/2) for up-to-date execution order and status. Each issue is labelled with its stage and priority.

---

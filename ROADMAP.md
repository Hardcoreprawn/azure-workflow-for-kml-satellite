# TreeSight - Development Roadmap

**Last updated:** 16 March 2026
**Status:** Active - Demo readiness and CI/CD reliability hardening

This roadmap is synchronized to the current GitHub issue backlog. The execution order below is dependency-first (not time-based).

> For agents: always pick the highest-priority OPEN item in the active execution wave, keep scope tight to that issue, and ensure CI passes (`uv run ruff check . && uv run pyright && uv run pytest tests/unit -v --tb=short`).

---

## Rules

1. One phase at a time for production-critical work.
2. Resolve blockers before optimization or expansion.
3. No scope creep outside the selected issue.
4. Every change must preserve deploy safety and observability.
5. CI must pass on every PR.

---

## Sync Snapshot (GitHub truth)

### Recently completed

- #131 closed: direct orchestration diagnostics payload
- #153 closed: minimal marketing website
- #154 closed: SWA deployment workflow
- #155 closed: contact form handler wiring
- #127 closed: Planetary Computer fix
- #128 closed: Planetary Computer URL signing fix
- #137 closed: infra migration to OpenTofu
- #138 closed: split dev/prd state containers
- #161 closed: Event Grid recreate propagation fix

### Roadmap hygiene

- #47 is still OPEN — do not mark closed.
- Non-existent issues #156–#160 removed from all references.

### Newly added (demo readiness)

- #201 closed: demo flow requires email and persists demo submissions
- #200 open: secure valet-token links for result delivery
- #199 open: TreeSight naming/trademark/domain conflict research

### Newly added (from recent Actions run analysis)

- #208 open: harden deploy fast-strategy readiness for sustained 404 startup windows
- #205 open: add retry/backoff resilience to website API contract verification step
- #206 open: publish actionable Trivy findings artifacts for scheduled base-image failures
- #207 open: add guardrails to prevent format-only CI failures on direct main pushes

---

## Active Execution Plan (Do Next, In Order)

### Wave 0 - Restore operational visibility ✅ COMPLETE

- #131 closed: direct orchestration diagnostics payload (anonymous JSON, no management URLs)
- #163 open: document readiness and diagnostics access model
- #164 open: post-deploy smoke checks for artifact verification

---

### Wave 1 - E2E pipeline verification (ENGINEERING COMPLETE, SIGN-OFF PENDING)

**Goal:** prove the deployed pipeline actually works end-to-end. Until this passes, all other work ships unverified software.

**Rationale for promotion:** Wave 0 restored observability. We can now see what a run produces. The E2E test is the first meaningful use of that surface. CI speed improvements (former Wave 1) are about iteration cost — valuable, but the pipeline correctness question is more urgent.

1. **#13** - end-to-end pipeline integration test (upload KML → verify GeoTIFF + metadata in blob storage) ✅
2. **#15** - error handling and retry logic verified under failure conditions ✅
3. **#14** - concurrent upload stress test (≥20 files) ✅
4. **#16** - logging and alerting validated with correlation IDs in App Insights ✅
5. **#17** - security review (Key Vault, Managed Identity, RBAC) ✅
6. **#19** - UAT sign-off (blocked on domain expert visual review/sign-off; automated UAT run complete)

**Exit criteria:**

- Automated test uploads `01_single_polygon_orchard.kml` and asserts GeoTIFF + metadata JSON appear at correct blob paths.
- Multi-feature KML (`03_multi_feature_vineyard.kml`) produces correct output count.
- All steps traceable via correlation ID in Application Insights.
- No open P0/P1 correctness bugs.

### Wave 2 - Delivery speed and CI throughput

**Goal:** reduce feedback/deploy latency. Now that correctness is proven, speed up the loop.

1. #152 - choose and implement native geospatial base image strategy
2. #150 - split CI into fast lane and native geospatial lane
3. #151 - automate base image refresh + vulnerability validation
4. #129 - enable Docker layer caching in deploy workflow
5. #130 - add smart deployment path selection (fast code-only vs full infra)
6. #148 - slim runtime Function image without regression

**Exit criteria:**

- Fast CI lane under 5 minutes for typical app-only PRs.
- Native lane still enforces geospatial/runtime correctness.
- Deploy workflow has measurable speed improvements with no readiness regressions.

### Wave 2.1 - CI/CD Reliability Hardening (NEW)

**Goal:** reduce flaky or low-signal pipeline failures observed in recent GitHub Actions runs.

1. #208 - harden deploy fast-strategy readiness for `/api/health` + `/api/readiness` 404 startup windows
2. #205 - make website API contract verification resilient to transient backend timeout
3. #206 - publish actionable Trivy findings artifacts and summaries on base-image scan failures
4. #207 - prevent format-only CI failures on `main` via branch/format guardrails

**Exit criteria:**

- Deploy fast strategy no longer fails solely on transient `404/404` warmup windows.
- Website deploy contract gate tolerates transient timeout but still fails on real version mismatch.
- Base-image refresh failures include downloadable vulnerability details sufficient for direct remediation.
- Format-only failures are caught before `main` red CI states.

### Wave 2.5 - Demo readiness and secure output delivery (NEW)

**Goal:** make the public demo trustworthy and easy to run live, with secure async result access.

1. #200 - secure valet-token results links + token validation path
2. #199 - branding due diligence for "TreeSight" and alternatives

**Exit criteria:**

- Demo submit path captures and validates a real email before accepting processing requests.
- Demo outputs are delivered via short-lived, scoped valet-token links (no direct storage credential exposure).
- Demo UX supports short in-page wait + async email completion fallback.
- Name risk assessment for "TreeSight" is documented with recommendation and alternatives.

### Wave 3 - Hardening and quality debt

**Goal:** close remaining quality/security/docs gaps before feature expansion.

1. #18 - docs runbook/API architecture updates
2. #47 - narrow `Any` usage at third-party boundaries
3. #132 - TypedDict to Pydantic migration (incremental, no behavior regressions)
4. #163 - document readiness and diagnostics access model
5. #164 - post-deploy smoke checks for artifact verification
6. #176 - UX output framing policy (square-framed AOI outputs, multipolygon split default)
7. #177 - optional H3-derived analytical outputs (AOI-first primary deliverables preserved)

**Exit criteria:**

- Testable, auditable production baseline with known security and observability posture.
- Remaining work is feature expansion, not reliability debt.

---

## Product Expansion Phases (After Waves 0-2)

These are sequenced by dependencies already captured in issue bodies and labels.

### Phase 5 - Multi-Tenant Foundation

**Gate:** operator-driven tenant provisioning works with isolated storage boundaries.

- #72 - tenant provisioning service

### Phase 6 - API and Authentication Foundation

**Gate:** authenticated API surface and identity model are in place.

- #73 - Entra External ID integration
- #74 - REST API layer (FastAPI on Container Apps)
- #75 - per-tenant quota enforcement and usage metering

### Phase 7 - Temporal Catalogue and NDVI

**Gate:** acquisitions are indexed and queryable over time with baseline analytics.

- #78 - temporal catalogue in Cosmos DB
- #79 - catalogue API endpoints
- #80 - NDVI computation activity
- #81 - scheduled re-acquisition

### Phase 8 - Tree Detection and Change Analysis

**Gate:** model-based tree analysis across time series is operational.

- #82 - tree detection model and inference pipeline
- #83 - tree health classification and temporal tracking
- #85 - change detection and temporal analysis

### Phase 9 - SaaS Monetization and Frontend

**Gate:** self-service SaaS experience with billing, annotation, and reporting.

- #76 - subscription tier logic
- #77 - Stripe billing integration
- #84 - annotation-driven model fine-tuning pipeline
- #86 - web frontend (React/Next.js)
- #87 - annotation tools and storage
- #88 - report generation and export

---

## Rust Service Stream (Parallel, Decision-Gated)

Do not start this stream until Waves 0-2 are complete or explicitly approved as strategic priority.

1. #143 - Phase 1 Rust WASM geodesic math service
2. #142 - Phase 2 Rust WASM KML parsing service
3. #144 - Phase 3 Rust raster processing service
4. #141 - Phase 4 production hardening for Rust services

Decision gate before starting:

- Confirm this migration is higher value than finishing current Python roadmap debt.
- Confirm rollback plan and dual-run validation budget are available.

---

## Current "Next 10" Pull Order

Use this exact queue unless blocked:

1. #208  (deploy fast-strategy readiness hardening)
2. #205  (website API contract timeout resilience)
3. #206  (Trivy actionable artifact/summaries)
4. #200  (valet-token result delivery)
5. #199  (name availability/conflict research)
6. #19   (human sign-off gate; unblock via domain expert review)
7. #152
8. #150
9. #151
10. #129

If blocked on an item, move to the next one and record the blocker in the issue.

---

## References

- System architecture: [PID.md](PID.md)
- Architecture review: [docs/reviews/ARCHITECTURE_REVIEW.md](docs/reviews/ARCHITECTURE_REVIEW.md)
- Operational readiness: [docs/OPERATIONAL_READINESS_ASSESSMENT.md](docs/OPERATIONAL_READINESS_ASSESSMENT.md)

# TreeSight - Development Roadmap

**Last updated:** 11 March 2026
**Status:** Active - Phase 4 (Operations reliability and delivery velocity)

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

- #153 closed: minimal marketing website
- #154 closed: SWA deployment workflow
- #155 closed: contact form handler wiring
- #127 closed: Planetary Computer fix
- #128 closed: Planetary Computer URL signing fix
- #137 closed: infra migration to OpenTofu
- #138 closed: split dev/prd state containers

### Roadmap hygiene actions required

- Remove references to non-existent issues #156, #157, #158, #159, #160, #161.
- Correct stale status entry for #47 (still OPEN, not completed).
- Keep phase labels aligned with issue labels (`phase-5` through `phase-9`) where those labels are already set.

---

## Active Execution Plan (Do Next, In Order)

### Wave 0 - Restore operational visibility (blocker wave)

**Goal:** regain confidence in remote verification and production diagnostics.

1. #131 - E2E manual test diagnostics blocked
2. Create follow-up issue: post-deploy smoke checks that validate output artifacts and auth path end-to-end
3. Create follow-up issue: explicit readiness/health access model documentation (public vs authenticated probe contract)

**Exit criteria:**

- We can verify a deployed orchestration run without manual guesswork.
- Smoke evidence is attached to each deploy (health, readiness, artifact existence).

### Wave 1 - Delivery speed and CI throughput

**Goal:** reduce feedback/deploy latency while keeping deterministic, secure builds.

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

### Wave 2 - Hardening debt still open from Phase 3

**Goal:** close foundational quality/security gaps that remain open.

1. #13 - end-to-end pipeline integration test
2. #15 - error handling and retry verification
3. #16 - logging and alerting validation
4. #17 - security review (Key Vault, MI, RBAC)
5. #14 - concurrent upload stress test
6. #18 - docs runbook/API architecture updates
7. #19 - UAT sign-off
8. #47 - narrow `Any` usage at third-party boundaries
9. #132 - TypedDict to Pydantic migration (incremental, no behavior regressions)

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

1. #131
2. #152
3. #150
4. #151
5. #129
6. #130
7. #148
8. #13
9. #15
10. #16

If blocked on an item, move to the next one and record the blocker in the issue.

---

## References

- System architecture: [PID.md](PID.md)
- Architecture review: [docs/reviews/ARCHITECTURE_REVIEW.md](docs/reviews/ARCHITECTURE_REVIEW.md)
- Operational readiness: [docs/OPERATIONAL_READINESS_ASSESSMENT.md](docs/OPERATIONAL_READINESS_ASSESSMENT.md)

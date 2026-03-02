# TreeSight — Development Roadmap

**Last updated:** 1 March 2026
**Status:** Active — Phase 3 in progress

> Sequenced delivery plan for TreeSight. The [PID](PID.md) defines the
> end-state; this document governs **execution order**. Each phase is
> a gate — nothing in Phase N starts until Phase N-1 is complete.
>
> **For agents:** pick the next open issue from the current phase,
> implement it, ensure CI passes (`uv run ruff check . && uv run pyright
> && uv run pytest tests/unit -v --tb=short`), then open a PR.

---

## Rules

1. **One phase at a time.** Complete all issues in the current phase before starting the next.
2. **Issues are self-contained.** Each issue has problem, scope, and acceptance criteria. Read the codebase to find implementation details — don't guess.
3. **No scope creep.** Only change what the issue asks for. Don't refactor adjacent code, add features, or "improve" things beyond the scope.
4. **CI must pass.** Every PR must pass: `ruff check`, `ruff format --check`, `pyright`, and `pytest tests/unit`.

---

## Current Phase: 3 — v1 Hardening

**Gate:** Engine passes PID acceptance criteria AC-1 through AC-12, deployed and observable.

**Work these issues (any order within the phase):**

| # | Title | Can start? | Status |
| - | ----- | ---------- | ------ |
| #102 | Consolidate `_int_cfg` / `_int_val` config helpers | Yes | ✅ DONE |
| #104 | Refactor `phases.py` — extract polling and error helpers | Yes | ✅ DONE |
| #105 | Add KML input validation (max file size, content checks) | Yes | ✅ DONE |
| #107 | Add health check endpoint (`/health`, `/readiness`) | Yes | ✅ DONE |
| #103 | Payload offload cleanup (blob lifecycle / TTL) | Yes | ✅ DONE |
| #108 | SkyWatch adapter: implement MVP or remove placeholder | Yes | ✅ DONE |
| #106 | Delete stale branches after merge | Yes | ✅ DONE |
| #13 | E2E pipeline integration test | Yes | |
| #15 | Error handling and retry logic verified | Yes | ✅ DONE |
| #16 | Logging and alerting configured and validated | Yes | ✅ DONE |
| #17 | Security review (Key Vault, Managed Identity, RBAC) | Yes | ✅ DONE |
| #18 | Documentation — architecture, runbook, API reference | Yes | |
| #14 | Concurrent upload stress test (≥ 20 files) | After #13 | |
| #19 | UAT sign-off | Last | |

### Phase 3 Done When

- [ ] All issues above are closed
- [ ] CI green on main
- [ ] Pipeline processes real KML end-to-end in deployed environment

---

## Phase 4 — Operational Maturity

**Gate:** Production-grade reliability before adding tenants.

| # | Title |
| - | ----- |
| #47 | Narrow `Any` usage at third-party boundaries |
| — | Semantic versioning for container images |
| — | Orchestration history purge strategy |
| — | Circuit breaker for imagery provider API failures |
| — | Integration test environment (staging) |

---

## Phase 5 — Multi-Tenant Foundation

**Gate:** Pipeline processes KML from any `{tenant}-input` container with isolated outputs.

| # | Title |
| - | ----- |
| #71 | Cosmos DB data layer setup (tenants + jobs containers only) |
| #72 | Tenant provisioning service (operator-triggered) |
| — | E2E test: two tenants process KML simultaneously, outputs isolated |

---

## Phase 6 — API & Authentication

**Gate:** Tenants self-register, authenticate, upload, and download via REST API.

| # | Title |
| - | ----- |
| #73 | Entra External ID integration |
| #74 | REST API layer (FastAPI on Container Apps) |
| #75 | Per-tenant quota enforcement and usage metering |

---

## Phase 7 — Temporal Catalogue & NDVI

**Gate:** Acquisitions indexed in Cosmos DB; NDVI computed automatically.

| # | Title |
| - | ----- |
| #78 | Temporal catalogue in Cosmos DB |
| #79 | Catalogue API endpoints |
| #80 | NDVI computation activity and analysis phase |
| #81 | Scheduled re-acquisition for temporal monitoring |

---

## Phase 8 — Tree Detection & Change Analysis

**Gate:** ML tree counting + multi-date comparison.

| # | Title |
| - | ----- |
| #82 | Tree detection model and inference pipeline |
| #83 | Tree health classification and temporal tracking |
| #85 | Change detection and temporal analysis |

---

## Phase 9 — SaaS Monetisation & Frontend

**Gate:** Full SaaS platform.

| # | Title |
| - | ----- |
| #76 | Subscription tier logic (Free / Pro / Enterprise) |
| #77 | Stripe billing integration |
| #84 | Annotation-driven model fine-tuning pipeline |
| #86 | Web frontend (React / Next.js) |
| #87 | Annotation tools and storage |
| #88 | Report generation and export (PDF, CSV, GeoJSON) |

---

## Phase Sequence

```text
Phase 3: Hardening ← YOU ARE HERE
    │
Phase 4: Operational Maturity
    │
Phase 5: Multi-Tenant Foundation
    │
Phase 6: API & Auth
    │
Phase 7: Catalogue & NDVI
    │
Phase 8: Tree Detection & Change Analysis
    │
Phase 9: SaaS (Frontend, Billing, Reports)
```

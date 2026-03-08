# TreeSight — Development Roadmap

**Last updated:** 8 March 2026
**Status:** Active — Phase 4 in progress (Operational Maturity)

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

## Current Phase: 4 — Operational Maturity

**Gate:** Production-grade monitoring, alerting, and incident response before multi-tenant deployment.

**Context:** [Operational Readiness Assessment](docs/OPERATIONAL_READINESS_ASSESSMENT.md) identified gaps from "infrastructure works" to "production-ready."

**Work these issues (priority order):**

### Priority 0 — Block Production

| # | Title | Status |
| - | ----- | ------ |
| #127 | Configure Azure Monitor Action Group with notification channels | 🔴 TODO |
| #128 | Wire existing metric alerts to Action Group | 🔴 TODO |
| #129 | Configure Event Grid dead letter queue | 🔴 TODO |
| #130 | Add Event Grid delivery failure alerts | 🔴 TODO |
| #131 | Create operational runbook | 🔴 TODO |

### Priority 1 — High

| # | Title | Status |
| - | ----- | ------ |
| #132 | Configure availability test for `/api/readiness` | 🟡 TODO |
| #133 | Add availability failure alert | 🟡 TODO |
| #134 | Add post-deployment smoke tests to CI/CD | 🟡 TODO |
| #135 | Add orchestration failure rate alert | 🟡 TODO |
| #136 | Add Activity timeout alert | 🟡 TODO |

### Priority 2 — Medium

| # | Title | Status |
| - | ----- | ------ |
| #137 | Configure consumption budget alerts | 🟢 TODO |
| #138 | Add storage growth monitoring | 🟢 TODO |

### Phase 4 Done When

- [ ] All P0 issues closed (alerts notify ops team)
- [ ] All P1 issues closed (automated monitoring)
- [ ] Runbook complete with triage procedures
- [ ] Post-deployment validation in CI/CD

---

## Phase 4 — Operational Maturity

**Gate:** Production-grade reliability, monitoring, and incident response capability before adding tenants.

### Completed

| # | Title | Status |
| - | ----- | ------ |
| #47 | Narrow `Any` usage at third-party boundaries | ✅ DONE |
| — | Semantic versioning for container images | ✅ DONE |
| — | Orchestration history purge strategy | ✅ DONE |
| — | Circuit breaker for imagery provider API failures | ✅ DONE |
| — | Integration test environment (staging) | ✅ DONE |

### P0 — Critical (Block Production)

**Context:** [Operational Readiness Assessment](docs/OPERATIONAL_READINESS_ASSESSMENT.md)

| # | Title | Effort | Impact |
| - | ----- | ------ | ------- |
| #127 | Configure Azure Monitor Action Group with notification channels (email, Teams webhook) | 15 min | Alerts fire but nobody is notified |
| #128 | Wire existing metric alerts to Action Group | 10 min | Alert notifications delivered to ops team |
| #129 | Configure Event Grid dead letter queue for failed webhook deliveries | 30 min | Silent event loss without dead lettering |
| #130 | Add Event Grid delivery failure metric alerts | 20 min | Detect webhook failures early |
| #131 | Create operational runbook (health checks, triage, recovery procedures) | 2-4 hrs | No incident response playbook exists |

### P1 — High (Should Fix Before Production)

| # | Title | Effort | Impact |
| - | ----- | ------ | ------- |
| #132 | Configure Application Insights availability test for `/api/readiness` endpoint | 30 min | Manual health verification currently |
| #133 | Add availability failure metric alert | 15 min | Automated outage detection |
| #134 | Add post-deployment smoke tests to Terraform apply workflow | 1 hr | Broken deploys not detected until manual testing |
| #135 | Add Durable Functions orchestration failure rate alert (log query) | 30 min | Pipeline failures not surfaced to ops |
| #136 | Add Activity timeout alert (log query) | 30 min | Stuck orchestrations not visible |

### P2 — Medium (Cost Management)

| # | Title | Effort | Impact |
| - | ----- | ------ | ------- |
| #137 | Configure Azure Consumption Budget with 80%/100% threshold alerts | 15 min | Uncontrolled spend risk |
| #138 | Add storage growth monitoring and retention policy | 30 min | Unbounded blob storage growth |

### Phase 4 Done When

- [ ] All P0 issues closed — alerts notify ops team, Event Grid has dead letter
- [ ] All P1 issues closed — automated health checks, CI validates deployments
- [ ] Runbook contains: health check procedures, incident triage, recovery steps, escalation matrix
- [ ] OpenTofu infrastructure includes: action group, availability tests, Event Grid dead letter, budget alerts
- [ ] Post-deployment CI job validates: health endpoint 200 OK, readiness checks pass
- [ ] On-call rotation established (or designated responder identified)

---

## Phase 5 — Multi-Tenant Foundation

**Gate:** Pipeline processes KML from any `{tenant}-input` container with isolated outputs.

| # | Title | Status |
| - | ----- | ------ |
| #71 | Cosmos DB data layer setup (tenants + jobs containers only) | ✅ DONE (Blob JSON MVP) |
| #72 | Tenant provisioning service (operator-triggered) | ✅ DONE |
| — | E2E test: two tenants process KML simultaneously, outputs isolated | ✅ DONE |

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
Phase 3: Hardening ✅ COMPLETE
    │
Phase 4: Operational Maturity ← YOU ARE HERE
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

# TreeSight — Development Roadmap

**Last updated:** 10 March 2026
**Status:** Active — Phase: Website & Marketing (in progress)

> **Strategic Pivot:** We have a working POC (Phase 3 ✅). Execution order:
> website + marketing → demo/ops that actually runs → features above the base.
>
> Sequenced delivery plan to go from working code to live product to SaaS. The [PID](PID.md) defines the end-state; this document governs **execution order**.
>
> **For agents:** pick the next open issue from the current phase, implement it, ensure CI passes (`uv run ruff check . && uv run pyright && uv run pytest tests/unit -v --tb=short`), then open a PR.

---

## Rules

1. **One phase at a time.** Complete all issues in the current phase before starting the next.
2. **Issues are self-contained.** Each issue has problem, scope, and acceptance criteria. Read the codebase to find implementation details — don't guess.
3. **No scope creep.** Only change what the issue asks for. Don't refactor adjacent code, add features, or "improve" things beyond the scope.
4. **CI must pass.** Every PR must pass: `ruff check`, `ruff format --check`, `pyright`, and `pytest tests/unit`.

---

## Current Phase: Website & Marketing

**Gate:** Live landing page, POC demo visibility, and early user interest capture.

**Context:** We have working code. Show it to the world. Let people request access. Keep ops simple (you + AI).

**Work these issues (priority order):**

| # | Title | Effort | Status |
| - | ----- | ------ | ------ |
| #153 | Create minimal marketing website (Astro/Next.js static HTML + live demo section) | 2-3 hrs | 🔴 TODO |
| #154 | Build Azure Function contact form handler (captures email, org, use case) | 1-2 hrs | 🔴 TODO |
| #155 | Deploy website to Azure Static Web Apps with live `/api/readiness` status badge | 30 min | 🔴 TODO |
| #156 | Add deployment verification smoke tests (POST to form, validate endpoints) | 1 hr | 🔴 TODO |

### Website & Marketing Done When

- [ ] Landing page deployed and live (DNS pointing to Static Web Apps)
- [ ] Contact form functional (captures to Azure Storage Table or email)
- [ ] Live `/api/readiness` status badge shows pipeline health on homepage
- [ ] E2E deployment test confirms form POST and health endpoint work
- [ ] Link to GitHub and early access request page visible

---

## Phase: Demo & Ops

**Gate:** Live pipeline runs reliably, ops team (you + AI) can sleep soundly.

**Context:** After website launch, build production ops using Azure AI Foundry (intelligent anomaly detection, incident classification, auto-remediation suggestions). Replaces manual Azure Monitor alert rules from old Phase 4.

**Work these issues (priority order):**

### Priority 0 — Ops Infrastructure

| # | Title | Effort | Status |
| - | ----- | ------ | ------ |
| #127 | Configure Azure Monitor Action Group with notification channels (Teams webhook to ops) | 15 min | 🔴 TODO |
| #128 | Wire Event Grid dead letter queue (DLQ) for failed webhook deliveries | 30 min | 🔴 TODO |
| #129 | Deploy Application Insights availability test for `/api/readiness` endpoint | 30 min | 🔴 TODO |
| #157 | Build AI Foundry ops layer: anomaly detection + incident classification + auto-remediation | 3-4 hrs | 🔴 TODO |
| #158 | Create ops AI dashboard (metrics, DLQ depth, latency p99, throughput, anomalies) | 2 hrs | 🔴 TODO |

### Priority 1 — Post-Deployment Validation

| # | Title | Effort | Status |
| - | ----- | ------ | ------ |
| #159 | Add smoke tests to CI/CD (health endpoint 200 OK after deploy) | 1 hr | 🔴 TODO |
| #160 | Add Durable Functions orchestration failure detection (AI alert) | 1 hr | 🔴 TODO |
| #161 | Add Activity timeout detection (AI alert) | 30 min | 🔴 TODO |

### Priority 2 — Cost Control

| # | Title | Effort | Status |
| - | ----- | ------ | ------ |
| #137 | Configure Azure Consumption Budget with 80%/100% alerts | 15 min | 🔴 TODO |
| #138 | Add storage growth monitoring + retention policy | 30 min | 🔴 TODO |

### Demo & Ops Done When

- [ ] Azure Monitor Action Group wired to Teams
- [ ] Event Grid dead letter queue configured
- [ ] AI Foundry ops layer deployed and alerting intelligently on Function metrics
- [ ] Live ops dashboard accessible (anomalies, incidents, DLQ depth)
- [ ] Post-deployment CI job validates health endpoint 200 OK
- [ ] You can push a deploy and not be on-call for 48hrs (AI handles triage)
- [ ] Cost alerts firing at 80%/100% of budget threshold

---

## Phase 5: Multi-Tenant & API Foundation

**Gate:** Pipeline processes KML from any `{tenant}-input` container with isolated outputs and self-service provisioning.

| # | Title | Effort |
| - | ----- | ------ |
| #72 | Tenant provisioning service (operator-triggered via CLI or Function) | 2 hrs |
| #73 | Entra External ID integration (B2B authentication) | 2-3 hrs |
| #74 | REST API layer (FastAPI on Container Apps with per-tenant auth) | 3-4 hrs |
| #75 | Per-tenant quota enforcement and usage metering | 1-2 hrs |
| — | E2E test: two tenants upload KML simultaneously, outputs fully isolated | 1 hr |

---

## Phase 6: Temporal Catalogue & Analytics

**Gate:** Acquisitions indexed in Cosmos DB, queryable by tenant/AOI/date, NDVI computed automatically.

| # | Title | Effort |
| - | ----- | ------ |
| #78 | Temporal catalogue in Cosmos DB (tenants + jobs + acquisitions) | 2-3 hrs |
| #79 | Catalogue API endpoints (list, filter by date range, AOI) | 2 hrs |
| #80 | NDVI computation activity and analysis phase | 2-3 hrs |
| #81 | Scheduled re-acquisition for temporal monitoring | 1-2 hrs |

---

## Phase 7: ML & Tree Detection

**Gate:** Automatic tree counting + multi-date comparison + change detection.

| # | Title | Effort |
| - | ----- | ------ |
| #82 | Tree detection model and inference pipeline (Planet or custom trained) | 4-6 hrs |
| #83 | Tree health classification and temporal tracking | 2-3 hrs |
| #85 | Change detection and temporal analysis (cross-date comparisons) | 2-3 hrs |

---

## Phase 8: SaaS Platform (Billing, Frontend, Reports)

**Gate:** Full self-service multi-tenant SaaS with billing and web UI.

| # | Title | Effort |
| - | ----- | ------ |
| #76 | Subscription tier logic (Free / Pro / Enterprise with quota limits) | 1 hr |
| #77 | Stripe billing integration | 2-3 hrs |
| #84 | Annotation-driven model fine-tuning pipeline | 3-4 hrs |
| #86 | Web frontend (React / Next.js) with authentication and tenant management | 4-6 hrs |
| #87 | Annotation tools and storage | 2-3 hrs |
| #88 | Report generation and export (PDF, CSV, GeoJSON) | 2-3 hrs |

---

## Completed (Phase 3 & Earlier)

| # | Title | Status |
| - | ----- | ------ |
| #47 | Narrow `Any` usage at third-party boundaries | ✅ DONE |
| #133 | Centralize WorkflowState enum, Protocol types, fix state-filter and polling bugs | ✅ DONE |
| — | Semantic versioning for container images | ✅ DONE |
| — | Orchestration history purge strategy | ✅ DONE |
| — | Circuit breaker for imagery provider API failures | ✅ DONE |
| — | Integration test environment (staging) | ✅ DONE |

---

## Phase Sequence

```text
Phase 3: Hardening & Core Pipeline ✅ COMPLETE
    │
Phase: Website & Marketing ← YOU ARE HERE
    │
Phase: Demo & Ops (AI-driven intelligent alerting)
    │
Phase 5: Multi-Tenant & API Foundation
    │
Phase 6: Temporal Catalogue & Analytics
    │
Phase 7: ML & Tree Detection
    │
Phase 8: SaaS Platform (Frontend, Billing, Reports)
```

---

## Reference

- **System architecture:** [PID.md §7](PID.md)
- **Architecture review:** [ARCHITECTURE_REVIEW.md](docs/reviews/ARCHITECTURE_REVIEW.md)
- **Operational readiness assessment:** [OPERATIONAL_READINESS_ASSESSMENT.md](docs/OPERATIONAL_READINESS_ASSESSMENT.md)

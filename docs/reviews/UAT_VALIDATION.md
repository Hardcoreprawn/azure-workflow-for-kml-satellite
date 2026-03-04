# Phase 3 UAT Validation Checklist

**Issue:** #19 — UAT sign-off
**Phase Gate:** All Phase 3 issues complete; pipeline ready for production hardening acceptance testing.

---

## Prerequisites

Before starting UAT, verify:

- [ ] All Phase 3 issues (#13–#18, #14, #15, #16, #17) are ✅ DONE in ROADMAP.md
- [ ] CI pipeline is green on main branch:
  - [ ] `ruff check .` → 0 errors
  - [ ] `pyright` → 0 errors
  - [ ] `pytest tests/unit` → all passing
  - [ ] `pytest tests/integration` → all passing
- [ ] Infrastructure-as-code compiles without errors:
  - [ ] `bicep build infra/main.bicep`
  - [ ] `bicep build infra/resources.bicep`
  - [ ] All Bicep modules compile and validate

---

## Acceptance Criteria

### AC-1: End-to-End Pipeline Execution

**Goal:** Verify the complete KML → imagery → metadata pipeline works in deployed environment.

**Test Steps:**

1. Upload a sample KML file to `{tenant}-input` blob container
2. Monitor Event Grid subscription for blob creation event
3. Verify Durable Functions orchestration triggers within 60 seconds
4. Observe orchestration stages complete:
   - Parse KML ✅
   - Prepare AOI ✅
   - Acquire imagery ✅
   - Poll order status (with retries) ✅
   - Download imagery ✅
   - Write metadata ✅

**Acceptance Criteria:**

- [ ] Pipeline completes successfully (orchestration state = `COMPLETED`)
- [ ] Imagery downloaded to `{tenant}-output` container
- [ ] Metadata JSON written alongside imagery blob
- [ ] No unhandled exceptions in Function App logs (Application Insights)
- [ ] Total latency ≤ 30 min (excluding imagery provider fulfillment time)

---

### AC-2: Concurrent Upload Resilience

**Goal:** Verify system handles ≥20 concurrent KML uploads without degradation or race conditions.

**Test Steps:**

1. Prepare 20+ distinct KML files (each 1–10 polygons)
2. Upload all concurrently to `{tenant}-input` container (e.g., via bulk blob copy or parallel HTTP PUT)
3. Monitor Function App metrics (duration, throughput, error rates)
4. Observe Application Insights logs for concurrent orchestration activity

**Acceptance Criteria:**

- [ ] All 20+ uploads process successfully
- [ ] No duplicate processing or missed uploads
- [ ] No timeout failures or retry exhaustion
- [ ] Function App remains responsive (latency p95 ≤ 10s for health check)
- [ ] No thread safety bugs or shared-state corruption in logs
- [ ] Imagery provider concurrency limits respected (if applicable)

---

### AC-3: Error Handling & Recovery

**Goal:** Verify graceful error handling with appropriate retry logic and alerting.

**Test Steps:**

1. **Transient Error Simulation:**
   - Temporarily disable imagery provider API endpoint
   - Monitor polling retry logic (exponential backoff, max retries)
   - Re-enable provider and observe successful recovery

2. **Non-Retryable Error Simulation:**
   - Upload malformed KML (syntax error, invalid schema)
   - Verify fail-fast behavior (no retry loop)
   - Observe error logged with clear diagnostics

3. **Metric Alert Validation:**
   - Trigger a failed request scenario
   - Verify Application Insights metric alert fires
   - Check alert notification delivery (email, webhook, etc.)

**Acceptance Criteria:**

- [ ] Transient errors retry with exponential backoff
- [ ] Non-retryable errors fail immediately with diagnostic messaging
- [ ] Failed orchestrations marked `FAILED` in history with error context
- [ ] High-latency requests trigger metric alert
- [ ] Failed-request count threshold triggers metric alert
- [ ] Alert notifications delivered to configured action group

---

### AC-4: Security Posture

**Goal:** Verify Key Vault, Managed Identity, and RBAC are correctly configured.

**Test Steps:**

1. **Key Vault Access:**
   - Verify Function App cannot directly access storage connection string (no plaintext in app settings)
   - Verify Function App Managed Identity has `Key Vault Secrets User` role
   - Test secret retrieval via Key Vault reference in app config (`@Microsoft.KeyVault(SecretUri=...)`)

2. **RBAC Role Assignments:**
   - List role assignments in Azure portal (Access Control > Role assignments)
   - Verify exactly 2 assignments (Storage Blob Data Contributor, Key Vault Secrets User)
   - Verify both target the Function App Managed Identity (ServicePrincipal)
   - Verify no over-privileged roles (Owner, Contributor, etc.)

3. **Blob Storage Security:**
   - Verify public blob access is disabled
   - Verify TLS 1.2 minimum enforced
   - Verify HTTPS-only traffic enforced
   - Verify no legacy access policies in Key Vault (RBAC-only mode)

**Acceptance Criteria:**

- [ ] No plaintext secrets in Function App app settings
- [ ] Function App Managed Identity successfully retrieves secrets from Key Vault
- [ ] Exactly 2 RBAC role assignments present and correct
- [ ] No access policies defined in Key Vault (RBAC-only)
- [ ] Blob storage public access disabled, TLS 1.2+, HTTPS-only
- [ ] Security scan reports 0 critical errors

---

### AC-5: Monitoring & Observability

**Goal:** Verify logs, metrics, and diagnostics are available for operational support.

**Test Steps:**

1. **Application Insights Telemetry:**
   - Execute a pipeline (end-to-end)
   - Open Application Insights trace/request view
   - Verify all orchestration stages appear in dependency graph
   - Verify custom events (e.g., KML parsing metadata) appear in logs

2. **Health Check Endpoints:**
   - Call `GET /api/health` → should return 200 OK
   - Call `GET /api/readiness` → should return 200 OK (if infrastructure ready)
   - Verify response includes version and service status

3. **Operational Runbook Procedures:**
   - Follow runbook step: "Check orchestration status"
   - Verify orchestration history query returns expected data
   - Follow runbook step: "Triage high latency"
   - Verify performance metrics are visible and actionable

**Acceptance Criteria:**

- [ ] Application Insights shows all pipeline stages as dependencies
- [ ] Custom events (KML parsing, AOI generation) logged and queryable
- [ ] Health check endpoints responsive and return expected status
- [ ] Readiness check reflects infrastructure state (e.g., storage account reachable)
- [ ] Runbook procedures executable and result in clear diagnostics
- [ ] Log queries available for common scenarios (failed orchestrations, latency analysis)

---

### AC-6: Documentation Completeness

**Goal:** Verify development and operational documentation is current and accurate.

**Test Steps:**

1. **README.md Coverage:**
   - Verify Architecture Reference section links to PID, architecture review, roadmap
   - Verify Operations Runbook section covers health checks, triage, recovery
   - Verify API Reference documents all endpoints, orchestrations, activities

2. **Code Comments:**
   - Sample key activities: `parse_kml`, `acquire_imagery`, `poll_order`
   - Verify docstrings document parameters, return values, exceptions
   - Verify error handling rationale is documented

3. **Infrastructure Documentation:**
   - Verify Bicep templates have descriptive comments
   - Verify parameter descriptions are clear
   - Verify outputs are documented

**Acceptance Criteria:**

- [ ] README contains Architecture Reference, Runbook, and API Reference
- [ ] All public functions have docstrings
- [ ] Error handling paths documented with rationale
- [ ] Bicep templates have descriptive comments
- [ ] No orphaned TODOs or FIXMEs in production code
- [ ] ROADMAP reflects all Phase 3 issues as ✅ DONE

---

## Sign-Off

### Development Sign-Off

- [ ] Code review complete (all PRs merged to main)
- [ ] All CI checks passing
- [ ] Test coverage ≥ 85% for orchestration logic
- [ ] No unresolved issues in code review

**Signed by:** ___________________  **Date:** _________

### QA/Testing Sign-Off

- [ ] All AC-1 through AC-6 criteria met
- [ ] No critical/high-severity bugs blocking production
- [ ] Performance validated under concurrent load
- [ ] Security posture verified

**Signed by:** ___________________  **Date:** _________

### Product/Stakeholder Sign-Off

- [ ] System meets Phase 3 gate requirements
- [ ] Pipeline processes real KML end-to-end successfully
- [ ] Ready for Phase 4 (Operational Maturity) work
- [ ] No showstoppers for future phases

**Signed by:** ___________________  **Date:** _________

---

## Known Limitations & Future Work

### Out of Scope (Phase 4+)

- [ ] Multi-tenant isolation (Phase 5)
- [ ] REST API authentication (Phase 6)
- [ ] Temporal catalogue (Phase 7)
- [ ] Tree detection & NDVI (Phase 8)

### Post-UAT Actions

1. **If Sign-Off Passes:**
   - Merge main branch
   - Deploy to staging environment
   - Begin Phase 4 work: Operational Maturity

2. **If Issues Found:**
   - Create GitHub issues for blockers
   - Return to Phase 3 roadmap for fixes
   - Re-run UAT validation

---

## References

- [PID.md](PID.md) — Product Requirements & Acceptance Criteria
- [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) — System Design & Rationale
- [README.md](README.md) — Operations Runbook & API Reference
- [ROADMAP.md](ROADMAP.md) — Phase 3 Delivery Plan
- [DEFENSIVE_CODE_REVIEW.md](DEFENSIVE_CODE_REVIEW.md) — Code Quality & Error Handling Audit

---

**Last Updated:** March 2, 2026  
**Phase:** 3 — v1 Hardening  
**Status:** Ready for UAT Execution

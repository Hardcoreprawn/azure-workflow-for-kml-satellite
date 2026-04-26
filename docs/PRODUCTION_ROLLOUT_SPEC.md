# Production Rollout Specification

**Date:** 2026-04-05  
**Status:** Proposed implementation spec  
**Scope:** Production deployment safeguards, preview-user feature rollout, live smoke validation, and automated promotion/demotion

---

## 1. Purpose

This specification defines how Canopex will:

1. verify a fresh production deployment with a real functional transaction before broad user exposure,
2. expose new features only to preview users or controlled rollout cohorts,
3. collect evidence about feature success and failure in production,
4. automatically stop promoting or actively disable failing features, and
5. promote features to normal users only after repeated successful live validation.

This is a repo-specific implementation plan, not a generic feature-flag overview. It is written against the current codebase, deployment workflow, and Azure topology.

---

## 2. Current State

The current repository already contains useful rollout building blocks:

- Live health and readiness checks with rollback in [.github/workflows/deploy.yml](.github/workflows/deploy.yml).
- Per-user persisted state patterns in [treesight/security/billing.py](treesight/security/billing.py) and [treesight/security/quota.py](treesight/security/quota.py).
- A narrow env-based feature gate in [treesight/security/feature_gate.py](treesight/security/feature_gate.py).
- Structured logging and correlation fields in [treesight/log.py](treesight/log.py).
- Production telemetry and alerts in [infra/tofu/main.tf](infra/tofu/main.tf).
- Local end-to-end trigger scripts in [scripts/simulate_upload.py](scripts/simulate_upload.py) and [scripts/load_baseline.py](scripts/load_baseline.py).

The current gaps are:

- Feature control is not generalised. It is one feature, one env variable.
- Deployment checks stop at process readiness, not real business-function validation.
- There is no first-class preview-user or cohort rollout model.
- There is no feature-specific success/failure evidence model for production promotion decisions.
- Automatic rollback exists for container readiness, but not for feature rollout state.

---

## 3. Goals

### 3.1 Functional goals

The system must:

1. keep new features off for normal users by default,
2. allow explicit enablement for preview users,
3. support gradual percentage rollout after preview,
4. verify a real production transaction after deployment,
5. record deployment- and feature-scoped outcomes in production telemetry,
6. automatically demote a feature when evidence indicates regression, and
7. promote a feature only after repeatable success.

### 3.2 Safety goals

The system must fail closed:

- if rollout state cannot be loaded, features remain off,
- if post-deploy functional smoke fails, the deployment is treated as unsafe,
- if telemetry queries fail, the controller must not promote features,
- if override state is malformed, affected features remain off.

### 3.3 Non-goals

This specification does not introduce:

- a public self-serve feature toggle UI for end users,
- A/B experimentation for marketing optimisation,
- cross-region active/active traffic shaping,
- blue/green website hosting beyond current deploy topology.

---

## 4. Architectural Approach

The rollout system will have four layers:

1. request-time feature evaluation in the app,
2. operator-managed preview and override state,
3. post-deploy live functional smoke execution,
4. a scheduled rollout controller that promotes or demotes features based on evidence.

### 4.1 Design principle

Evaluation is synchronous and conservative. Promotion is asynchronous and evidence-driven.

The request path should answer only this question:

"Is feature X enabled for this request right now?"

The rollout controller answers a separate question:

"Should feature X be promoted, held, or demoted based on live evidence?"

---

## 5. Rollout Data Model

Rollout state will live in storage, not environment variables.

### 5.1 Containers

Add two Cosmos containers when Cosmos is enabled:

- `feature_flags`
- `feature_flag_overrides`

Fallback path when Cosmos is unavailable:

- `pipeline-payloads/feature-flags/{feature_name}.json`
- `pipeline-payloads/feature-flag-overrides/{user_id}.json`

This mirrors the existing Cosmos-or-blob fallback pattern used in [treesight/security/billing.py](treesight/security/billing.py) and [treesight/security/quota.py](treesight/security/quota.py).

### 5.2 Feature flag document

Each feature has one canonical document keyed by feature name.

```json
{
  "id": "scheduled-monitoring-v2",
  "feature_name": "scheduled-monitoring-v2",
  "status": "off",
  "variant": "control",
  "description": "Next iteration of scheduled monitoring workflow",
  "default_value": false,
  "allow_anonymous": false,
  "preview_enabled": true,
  "rollout_pct": 0,
  "cohort_seed": "user_id",
  "kill_switch": false,
  "requires_smoke_success": true,
  "min_successful_smokes": 3,
  "max_error_rate_pct": 2.0,
  "max_p95_latency_ms": 8000,
  "min_preview_sample_size": 20,
  "evaluation_mode": "server",
  "created_at": "2026-04-05T00:00:00Z",
  "updated_at": "2026-04-05T00:00:00Z",
  "updated_by": "github-actions/deploy"
}
```

### 5.3 Status values

Supported `status` values:

- `off`
- `preview_only`
- `percentage_rollout`
- `on`
- `blocked`

`blocked` means automatic promotion is disabled until a human explicitly clears the feature.

### 5.4 Override document

Each override document is keyed by user id.

```json
{
  "id": "user-123",
  "user_id": "user-123",
  "features": {
    "scheduled-monitoring-v2": {
      "enabled": true,
      "variant": "preview",
      "reason": "internal-preview",
      "expires_at": "2026-05-01T00:00:00Z"
    }
  },
  "updated_at": "2026-04-05T00:00:00Z",
  "updated_by": "operator"
}
```

Expired overrides are ignored at evaluation time.

### 5.5 Smoke run record

Each production smoke run produces a durable evidence record.

Storage path:

- `pipeline-payloads/deploy-smoke/{deploy_sha}/{run_id}.json`

Minimum fields:

```json
{
  "run_id": "20260405T101500Z-main-abc1234",
  "deploy_sha": "abc1234",
  "environment": "prd",
  "base_url": "https://func-kmlsat-prd.azurewebsites.net",
  "started_at": "2026-04-05T10:15:00Z",
  "completed_at": "2026-04-05T10:17:12Z",
  "success": true,
  "instance_id": "f3f0f8b0-...",
  "checks": {
    "health": true,
    "readiness": true,
    "submit": true,
    "orchestrator_completed": true,
    "artifacts_present": true
  },
  "artifacts": {
    "metadata": "...",
    "manifest": "..."
  },
  "failure_reason": ""
}
```

---

## 6. Feature Evaluation Rules

Feature evaluation will be implemented in a shared runtime module that generalises the current logic in [treesight/security/feature_gate.py](treesight/security/feature_gate.py).

### 6.1 Inputs

The evaluator must accept:

- `feature_name`
- `user_id`
- request metadata where needed
- deployment metadata such as git sha

### 6.2 Evaluation order

Evaluation order is strict:

1. If `kill_switch` is true, return disabled.
2. If feature document is missing or unreadable, return disabled.
3. If a valid per-user override exists, return the override decision.
4. If `status` is `off` or `blocked`, return disabled.
5. If `status` is `preview_only`, return enabled only for explicit preview overrides.
6. If `status` is `percentage_rollout`, enable deterministically for users whose rollout bucket falls within `rollout_pct`.
7. If `status` is `on`, return enabled.

### 6.3 Bucketing

Percentage rollout must be deterministic.

Bucket input:

- `sha256("{feature_name}:{user_id}") % 100`

This ensures that a given user stays in or out of the same rollout cohort unless the percentage changes.

### 6.4 Anonymous users

Anonymous users are not eligible for preview-only features unless a feature explicitly declares `allow_anonymous=true`.

### 6.5 Failure mode

If any storage read fails unexpectedly, the evaluator returns disabled and logs a structured `feature_eval_failed` event.

---

## 7. Operator Control Surface

Preview assignment and rollout updates must not be performed through a public user endpoint.

### 7.1 Phase 1 control surface

Initial implementation uses operator-only scripts or GitHub Actions.

Required scripts:

- `scripts/feature_flag_upsert.py`
- `scripts/feature_flag_override.py`
- `scripts/feature_flag_clear_override.py`

These scripts must authenticate using the same environment model already used by deployment automation.

### 7.2 Future control surface

If an API is later introduced, it must:

- require strong operator/admin authentication,
- record `updated_by`,
- reject wildcard or bulk changes without explicit confirmation,
- never be callable by ordinary product users.

### 7.3 Billing emulation precedent

The account-locked emulation endpoint in [blueprints/billing.py](blueprints/billing.py) is a useful storage pattern reference, but it must not be reused as the production admin surface because it is intentionally restricted to explicitly allowlisted operator accounts.

---

## 8. Post-Deploy Functional Smoke

Current deployment already verifies `health` and `readiness` and rolls back the container on failure in [.github/workflows/deploy.yml](.github/workflows/deploy.yml).

This specification extends deploy with a second gate: a real functional smoke transaction.

### 8.1 Smoke flow

After readiness passes, deploy must:

1. upload or submit a fixed known-good KML,
2. trigger the production workflow,
3. record the returned instance id,
4. poll [blueprints/pipeline/diagnostics.py](blueprints/pipeline/diagnostics.py) until terminal state,
5. require `runtimeStatus=Completed`,
6. validate required artifact paths in storage,
7. persist the smoke evidence record,
8. continue deployment only if the smoke succeeds.

### 8.2 Smoke path selection

Preferred production smoke path:

- submit through the same public app path that real users use,
- avoid hidden bypasses,
- use a dedicated smoke identity or smoke tenant,
- tag the run as `smoke=true` in structured telemetry.

If public submission cannot yet be used in production automation, an interim script may trigger through the existing blob/event path, but the target state is user-path validation.

### 8.3 Required checks

Minimum deploy smoke assertions:

1. `GET /api/health` returns 200.
2. `GET /api/readiness` returns 200.
3. smoke submission returns accepted/success.
4. orchestration reaches `Completed`.
5. output artifact paths are present.
6. no protected admin/runtime endpoint becomes anonymously accessible.

### 8.4 Failure handling

If functional smoke fails:

- mark deployment unsafe,
- rollback container image using the existing rollback path,
- leave all new feature documents at `off` or `blocked`,
- write the failure evidence record,
- emit a high-severity alert.

---

## 9. Telemetry and Evidence Model

The rollout system is only as good as its evidence. Every feature decision and every smoke run must be observable.

### 9.1 Required structured fields

Add these structured properties where applicable:

- `feature_name`
- `feature_status`
- `feature_variant`
- `feature_enabled`
- `preview_user`
- `rollout_pct`
- `deploy_sha`
- `environment`
- `instance_id`
- `correlation_id`
- `smoke`
- `user_id_hash`

`user_id_hash` must be a one-way hash. Raw user ids must not be emitted into broad telemetry unless already required for operational reasons.

### 9.2 Event types

Required event classes:

- `feature_evaluated`
- `feature_eval_failed`
- `deploy_smoke_started`
- `deploy_smoke_completed`
- `deploy_smoke_failed`
- `feature_promoted`
- `feature_demoted`
- `feature_blocked`

### 9.3 Metrics used by rollout controller

Per feature and environment, the controller must query:

- request count,
- success count,
- failure count,
- error rate,
- p50 latency,
- p95 latency,
- count of smoke successes,
- count of smoke failures.

### 9.4 Existing infra reuse

The design must reuse existing Application Insights and Azure Monitor plumbing already defined in [infra/tofu/main.tf](infra/tofu/main.tf), adding queries and alerts rather than introducing a second observability stack.

---

## 10. Automated Promotion and Demotion

Promotion and demotion happen in a scheduled controller, not inline with user requests.

### 10.1 Controller execution model

Run on a schedule, initially via GitHub Actions or a Timer Trigger.

Frequency:

- every 15 minutes for smoke result ingestion,
- hourly for feature promotion/demotion evaluation.

### 10.2 Promotion rules

A feature may move from `preview_only` to `percentage_rollout` only if all of the following are true:

1. `requires_smoke_success` is satisfied,
2. there are at least `min_successful_smokes` consecutive successful deploy smokes,
3. preview cohort error rate is below `max_error_rate_pct`,
4. preview cohort p95 latency is below `max_p95_latency_ms`,
5. preview sample size is at least `min_preview_sample_size`.

Initial promotion ladder:

- `preview_only`
- `percentage_rollout` at 5%
- `percentage_rollout` at 25%
- `percentage_rollout` at 50%
- `on`

### 10.3 Demotion rules

Automatic demotion must occur if any of the following are true:

- latest deploy smoke failed,
- feature error rate exceeds threshold,
- feature p95 latency exceeds threshold,
- repeated feature evaluation failures indicate storage/config breakage.

Demotion path:

- `on` -> `percentage_rollout` at previous safe level,
- `percentage_rollout` -> `preview_only`,
- `preview_only` -> `blocked` if the failure is severe or repeated.

### 10.4 Human override

Operators must be able to:

- block a feature immediately,
- clear a block after investigation,
- set rollout percentage explicitly,
- disable automatic promotion for a specific feature.

---

## 11. Security Requirements

### 11.1 Default posture

The rollout system must fail closed.

### 11.2 Data handling

- No public endpoint may allow arbitrary feature enablement.
- Override writes must be authenticated and auditable.
- Telemetry must avoid leaking raw PII where not operationally required.
- Preview-user assignment must use stable authenticated user ids from [treesight/security/auth.py](treesight/security/auth.py).

### 11.3 Protected surface checks

Deploy smoke must verify that protected runtime endpoints remain protected after rollout, consistent with the intent already documented in [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md).

---

## 12. Repository Changes Required

### 12.1 New runtime modules

- `treesight/security/feature_flags.py`
- `treesight/security/feature_flag_store.py`
- `treesight/security/feature_flag_models.py`

### 12.2 Changes to existing modules

- Generalise [treesight/security/feature_gate.py](treesight/security/feature_gate.py) or replace it with the new feature evaluator.
- Update feature-owning endpoints to call the shared evaluator.
- Extend [treesight/log.py](treesight/log.py) call sites to include rollout fields.
- Extend [.github/workflows/deploy.yml](.github/workflows/deploy.yml) with post-readiness functional smoke.
- Add Cosmos containers and outputs in [infra/tofu/main.tf](infra/tofu/main.tf).

### 12.3 New scripts

- `scripts/feature_flag_upsert.py`
- `scripts/feature_flag_override.py`
- `scripts/feature_flag_clear_override.py`
- `scripts/production_smoke_test.py`

### 12.4 Tests

Required test areas:

- feature evaluation precedence,
- deterministic percentage bucketing,
- expired override handling,
- fail-closed storage errors,
- deploy smoke success path,
- deploy smoke failure path and rollback behavior,
- controller promotion and demotion logic,
- endpoint enforcement when UI hides but backend must still reject.

---

## 13. Implementation Phases

### Phase A - Shared rollout engine

Deliverables:

- storage-backed feature definitions,
- per-user preview overrides,
- shared evaluator,
- unit tests.

Acceptance:

- current billing gate can be expressed using the new system,
- storage failure keeps billing disabled,
- preview user can be enabled without env changes.

### Phase B - Production smoke gate

Deliverables:

- production smoke script,
- deploy workflow integration,
- smoke evidence record,
- rollback-on-functional-failure.

Acceptance:

- deploy does not complete after readiness alone,
- failed smoke leaves the previous image live,
- successful smoke leaves an evidence artifact tied to deploy sha.

### Phase C - Telemetry and controller

Deliverables:

- feature-scoped telemetry,
- rollout controller,
- promotion/demotion rules,
- alerts.

Acceptance:

- controller can promote a feature from preview to 5%,
- controller can demote a feature automatically after regression,
- operator can block promotion manually.

### Phase D - Feature adoption

Deliverables:

- migrate current gates to shared engine,
- add rollout metadata to new risky features by default,
- update operational docs.

Acceptance:

- no new high-risk feature ships without a rollout document and kill switch,
- runbook matches the implemented deploy smoke behavior.

---

## 14. Open Questions

These do not block Phase A but must be resolved before full rollout automation:

1. Should production smoke use the public authenticated submission path immediately, or use the current blob/event path as an interim step?
2. Should rollout control live in GitHub Actions only, or also in a Timer Trigger inside the app?
3. Which features are mandatory to register in the rollout system from day one beyond billing?
4. Should website-only features remain flag-gated inside the current static site, or require a distinct staging website before launch?

---

## 15. Acceptance Summary

This specification is satisfied when all of the following are true:

1. Deploy validates a real production transaction after readiness.
2. New features default to off and can be granted to preview users without code or env changes.
3. Feature enablement is enforced server-side.
4. Rollout decisions are backed by production telemetry, not intuition.
5. Failing features can be automatically demoted or blocked.
6. Normal users do not receive new features until the system has repeated evidence that they work.

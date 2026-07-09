# ADR 0004: Harness Reusability — Portable Toolkit vs Project-Specific Deployment

## Status

Accepted (2026-07-03)

## Context

ADR 0003 named three bounded contexts (engine / app / harness) and framed the
repo-split criteria around the *engine* gaining a second consumer. In practice
the **harness is the most reusable of the three** — it encodes engineering
*process* (how we triage, prioritise, gate, and prove work), not domain logic.
The engine is geospatial-specific and the app is Canopex-specific, but the
harness is largely project-agnostic.

However, not all of the harness is portable. It divides into a generic toolkit
and glue specific to this app's deployment substrate.

## Decision

Treat the harness as two sub-layers, and keep the portable layer extractable.

### 1. Portable engineering toolkit (reusable in any repo)

- `scripts/backlog_autopilot.py` — dispatches purely off labels
  (`moscow:*` / `priority:*` / `domain:*`), no domain knowledge.
- The prioritisation model (#1010): planned/unplanned × delivery/ops quadrants,
  MoSCoW, the `domain:*` axis, security floor + cap, oldest-first.
- PR/CI assurance patterns: the `no-autopilot` gate, require-linked-issue,
  PR watchdog, **make-standardization** (CI calls `make` targets so local == CI),
  scanner consistency (pinned Trivy/Semgrep run via `make`), the actionlint gate.
- Agent customization (`.github/instructions`, skills, agents) + memory
  conventions.

### 2. Project-specific deployment harness (not portable as-is)

- `deploy.yml`, `infra/tofu/` — bound to this app's Azure Functions on
  Container Apps + SWA.
- `pipeline_smoke.py` / `e2e_smoke_gate.py` / `container_smoke_test.py` —
  reference this app's endpoints and blob layout.
- `trivyignore`, base-image / image config — this app's dependencies.

### 3. Discipline now: parameterise, don't hardcode

New portable-harness work must take repo name, label names, and paths as
**workflow inputs / repo variables**, not hardcoded Canopex assumptions, so a
future lift is copy-paste-and-parameterise rather than untangle.

### 4. Extraction form and trigger

- **Form (when extracted):** a template repo + reusable workflows
  (`workflow_call`) + composite actions + a small installable autopilot
  package, consumed by other repositories.
- **Trigger:** a *second project* wants it (this is the ADR 0003 split
  criterion; the harness — not the engine — is the leading candidate).
- **Until then:** stay in-repo (solo maintainer, pre-launch, app currently
  offline). Extraction now would cost more than it returns.

## Consequences

**Positive**

- A future lift into a shared repo/template is cheap because the portable layer
  is kept decoupled from the start.
- Clear line between "engineering process we'd reuse" and "this app's deploy
  glue," so we don't accidentally bake Canopex specifics into reusable pieces.

**Negative / costs**

- Parameterisation adds small overhead to harness work now (inputs/vars instead
  of literals).
- Two sub-layers to keep straight within the single `harness` domain label.

## Related

- ADR 0003 (three bounded contexts)
- #1026 (tracking: keep the generic harness project-agnostic)
- #1010 (prioritisation), #1004 / #1007 (PR/CI assurance)

---
description: "Use when editing GitHub Actions workflows, OpenTofu infrastructure, deployment scripts, rollout controls, runtime readiness checks, or observability tied to dev/prod promotion and release safety."
name: "Release Safety"
applyTo:
  - ".github/workflows/**"
  - "infra/tofu/**"
  - "scripts/reconcile_eventgrid_subscription.py"
  - "scripts/validate_dev_infra_gate.py"
  - "docs/OPERATIONS_RUNBOOK.md"
---
# Release Safety Guidelines

- Preserve the distinction between build, deploy, and promote. Production should promote the same built artifact, not rebuild ad hoc.
- Do not introduce shared-environment deploy paths for PR branches unless the user explicitly wants a break-glass path.
- Every rollout change should answer four questions: what is deployed, how it is validated, how it is rolled back, and who owns the decision to proceed.
- Keep deploy evidence trustworthy: structured logs, runtime smoke checks, and explicit failure messages matter as much as the happy path.
- When changing deploy or infra behavior, update the matching runbook or roadmap note in the same change.

## Required Checks

- Name the target environment and whether the change affects dev, prod, or promotion between them.
- Add or update the narrowest test, validation script, or workflow assertion that proves the intended behavior.
- Call out any security, billing, or feature-exposure side effects explicitly.

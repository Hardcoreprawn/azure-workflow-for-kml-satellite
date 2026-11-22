---
name: "Docs Drift Audit"
description: "Audit behavior, contract and operational docs drift with Hamilton."
argument-hint: "PR, issue, feature, or changed files"
agent: "Hamilton"
---
Audit the supplied change for docs and contract drift.

- Compare canonical `docs/API_INTERFACE_REFERENCE.md`, `docs/openapi.yaml`, `docs/OPERATIONS_RUNBOOK.md`, and matching tests as applicable.
- Identify which source-of-truth docs should have moved.
- Flag missing updates to API reference, runbook, OpenAPI, README, or tests.
- Review roadmap status or GitHub Project bookkeeping only when explicitly requested; missing per-merge updates are not delivery blockers.
- Separate hard blockers from acceptable follow-up work.
- End with the exact files that should be updated before merge.

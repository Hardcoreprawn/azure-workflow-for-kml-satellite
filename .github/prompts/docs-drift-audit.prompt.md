---
name: "Docs Drift Audit"
description: "Audit a PR, issue, or feature for docs, contract, and roadmap drift using the Contract and Docs Keeper agent."
argument-hint: "PR, issue, feature, or changed files"
agent: "Contract and Docs Keeper"
---
Audit the supplied change for docs and contract drift.

- Identify which source-of-truth docs should have moved.
- Flag missing updates to roadmap status, API reference, runbook, OpenAPI, README, or tests.
- Separate hard blockers from acceptable follow-up work.
- End with the exact files that should be updated before merge.

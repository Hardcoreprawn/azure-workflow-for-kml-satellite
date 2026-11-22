---
name: "Release Gate Audit"
description: "Audit rollout and promotion safety in one pass with Hamilton."
argument-hint: "Workflow, PR, issue, or deploy change"
agent: "Hamilton"
---
Audit the supplied deployment or promotion change for release safety.

- Read `.github/instructions/release-safety.instructions.md` and `docs/OPERATIONS_RUNBOOK.md`.
- Identify which environments and promotion paths it touches.
- Check for artifact-promotion, smoke-test, rollback, and observability gaps.
- Call out accidental PR-branch exposure to shared environments.
- List the gates that should be required before merge or deploy.
- End with a go/no-go recommendation and the reason.

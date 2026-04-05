---
name: "Release Gate Audit"
description: "Audit a workflow, PR, or deployment-related change for rollout and promotion safety using the Release Safety Guard agent."
argument-hint: "Workflow, PR, issue, or deploy change"
agent: "Release Safety Guard"
---

# Release Gate Audit

Audit the supplied deployment or promotion change for release safety.

- Identify which environments and promotion paths it touches.
- Check for artifact-promotion, smoke-test, rollback, and observability gaps.
- Call out accidental PR-branch exposure to shared environments.
- List the gates that should be required before merge or deploy.
- End with a go/no-go recommendation and the reason.

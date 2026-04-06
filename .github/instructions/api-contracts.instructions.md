---
description: "Use when editing API endpoints, auth behavior, request or response payloads, OpenAPI definitions, contract tests, or public integration docs."
name: "API Contract Discipline"
applyTo:
  - "blueprints/**"
  - "docs/openapi.yaml"
  - "docs/API_INTERFACE_REFERENCE.md"
---
# API Contract Guidelines

- Keep code, tests, and contract docs aligned. If endpoint behavior changes, update the matching tests and docs in the same change.
- Preserve backward compatibility unless the issue explicitly authorizes a breaking change.
- Make auth, quota, and billing effects explicit in both code review and docs.
- Prefer explicit validation and typed request/response handling over loose payload parsing.

## Required Checks

- Update endpoint tests or integration tests for any behavior change.
- Reconcile public docs with live route and auth behavior.
- Call out migration or client-impact risk in the PR description when request or response shapes move.

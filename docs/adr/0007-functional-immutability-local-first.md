# ADR 0007: Functional Immutability and Local-First Schema Evolution

## Status

Accepted

## Context

This project is still pre-live and primarily exercised in local mode.

In this stage, we optimize for development speed, debuggability, and
predictable AI-assisted iteration. We have repeatedly seen that mutable
state and broad compatibility layers make the system harder to reason about,
harder to test, and harder for both humans and AI agents to debug.

## Decision

Adopt the following defaults for all new work and touched files:

1. Functional, immutable core logic by default.
2. No in-place mutation of input arguments, shared state, or passed-in
   dictionaries/lists in core logic.
3. Prefer explicit typed models and pure transforms over ad-hoc mutable maps.
4. Prefer fail-fast behavior over permissive fallback behavior.
5. Avoid compatibility and interop shims unless they are strictly required by
   an external boundary (for example: third-party webhook payloads,
   infrastructure contracts, or persisted production data).
6. Because we are pre-live and local-first, schema evolution should normally be
   direct: update producers, consumers, fixtures, and tests in one coherent
   change rather than maintaining dual-read or dual-write code paths.

## Guardrails

When compatibility code is genuinely required, it must be:

1. Narrowly scoped to the boundary that needs it.
2. Explicitly documented in a short comment explaining why it exists.
3. Treated as temporary, with a follow-up issue to remove it.

## Consequences

Positive:

- Smaller state surface area and fewer hidden side effects.
- Simpler debugging and clearer causal flow.
- Lower maintenance overhead from stale migration paths.
- Better fit for AI-assisted coding, review, and refactoring.

Trade-offs:

- Internal schema changes can be breaking during development.
- Feature branches may need coordinated updates across tests and callers.
- Some convenience fallbacks are intentionally removed in favor of explicit
  errors and fast feedback.

## Implementation Notes

- Apply this rule opportunistically: when touching a file, improve mutation
  hotspots and remove avoidable compatibility branches in that scope.
- Do not perform wide, unrelated rewrites just to satisfy this ADR.
- Keep behavior changes covered by focused tests.

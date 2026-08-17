# Execution Brief Template

## Context

- Roadmap stage:
- Issue or target:
- Primary persona:
- Job-to-be-done:

## Owning Anchor

<!-- The single file, symbol, endpoint, workflow, or failing command that directly controls
     the behavior being changed. One entry. -->

## User Problem

- What the user cannot do today:
- Why it matters operationally:
- What evidence will show the problem is improved:

## Observable Problem

- Current behavior:
- Repro / evidence (log line, test name, CI URL):

## Acceptance Signal

<!-- Measurable behavior — test name, command output, or metric. -->

## First Focused Check

<!-- Exact narrow command expected to FAIL before and PASS after. One line. -->

## Owning Surfaces

- Primary code paths:
- Primary docs or contract files:
- Runtime or rollout surfaces:

## Ordered Slices

1. Slice one:
2. Slice two:
3. Slice three:

## Validation Gates

- Narrow executable validation per slice:
- Handoff: `make check`
- Release or rollout checks:
- Docs or contract checks:

## Risk Class

<!-- low | normal | high | release-critical -->

## Non-Goals

<!-- Adjacent work explicitly excluded from this PR. -->

## Risks

- Main implementation risk:
- Main rollout risk:
- Main persona-fit risk:

## Dependencies

<!-- Blocked by #N / Depends on #N in issue body (not comments). Write "none" if no prerequisites. -->

Depends on: none

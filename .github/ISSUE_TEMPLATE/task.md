---
name: Work item
about: Feature, chore, refactor, or discovered bug — captures the info the backlog autopilot and reviewers need
title: ''
labels: []
---

<!-- markdownlint-disable MD041 -->
## Summary

<!-- What needs doing and why, in a sentence or two. -->

## Persona & job-to-be-done

<!-- Which persona this serves and the job it improves. See docs/PERSONA_DEEP_DIVE.md.
     Persona options: conservation / ESG-EUDR / agricultural-advisor / operator-dev.
     For purely internal maintenance where developer JTBD is self-evident, write "operator-dev". -->

- Persona:
- Job-to-be-done:

## Owning anchor

<!-- The single file, symbol, endpoint, workflow, or failing command that directly controls
     the behavior being changed. A coding agent uses this to navigate without broad exploration.
     Example: "blueprints/pipeline/submission.py → submit_analysis()" or "make check → ruff E501" -->

## Observable problem

<!-- Current behavior and a minimal repro or evidence pointer (log line, failing test name,
     screenshot, CI run URL). Be specific enough that a coding agent can reproduce it. -->

- Current behavior:
- Repro / evidence:

## Acceptance signal

<!-- Measurable behavior — not prose-only completion. Prefer a test name, command output,
     or metric threshold. Example: "pytest tests/test_parsers.py::test_rejects_zip_bomb passes" -->

## First focused check

<!-- The exact narrow test or command expected to FAIL before the change and PASS afterward.
     One line. Example: "make test-fast TESTS=tests/test_parsers.py::test_rejects_zip_bomb" -->

## Handoff checks

<!-- Exact broader commands required before review. Default set: -->

- [ ] `make check` passes locally

## Risk class

<!-- low | normal | high | release-critical -->

Risk:

## Non-goals

<!-- Adjacent work explicitly excluded from this PR. Helps reviewers spot scope creep. -->

## Dependencies

<!-- CRITICAL for ordering. The backlog autopilot reads THIS ISSUE BODY (not comments)
     and will NOT auto-assign this issue while any blocker below is still open.
     Use the exact form "Blocked by #N" or "Depends on #N", one per line.
     Write "none" if there are no prerequisites. -->

Depends on: none

<!--
Before submitting, add labels so the autopilot can rank and gate this issue:
  • MoSCoW (eligibility): moscow:must | moscow:should | moscow:could | moscow:wont
  • priority:now | priority:next | priority:backlog (refines order within a tier)
  • blocked — set this if a prerequisite is not yet done (also honoured by the autopilot)
  • no-autopilot — for infra / OpenTofu / CI / workflow work that needs human design
-->

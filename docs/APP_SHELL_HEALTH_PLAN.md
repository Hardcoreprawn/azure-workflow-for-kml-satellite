# App Shell Health Plan

## Goal

Break `website/js/app-shell.js` into modules that are safe to change independently, without losing business context (auth, billing, run lifecycle, evidence, EUDR workflows).

Design for app-centric modularity: EUDR, conservation, and future apps must be able to diverge in UI and behavior without re-entangling shared pipeline logic.

This plan assumes the site is not yet live and favors clarity and maintainability over transition complexity.

## Current Problem

`app-shell.js` currently mixes:

- auth bootstrap and session UX
- API client fallback and request handling
- billing and tier emulation UI
- analysis submission and polling lifecycle
- history and selection state
- evidence map and timelapse controls
- per-AOI notes and human override workflows
- EUDR-specific usage and exports
- DOM binding and app boot orchestration

This causes high coupling, high regression risk, and slow review/debug cycles.

## Target Architecture

Keep vanilla JS, no build step. Split by domain and expose one narrow public API per file.

### Architecture Principle: App-Centric on Shared Pipeline

- Treat each app as a product surface (EUDR, conservation, portfolio, future apps).
- Treat the pipeline lifecycle as a shared platform service.
- App-specific decisions must live in app modules, not in shared run/pipeline modules.
- Shared modules must not branch on app identity except through a single app contract.

This enables two valid deployment shapes without rework:

- Profile model: one shell, multiple app profiles.
- Fully separated apps: distinct shells per app, each importing only shared pipeline/auth/billing primitives.

### Proposed Files

- `website/js/app-core-state.js`
- `website/js/app-core-dom.js`
- `website/js/app-profiles.js`
- `website/js/app-auth.js`
- `website/js/app-billing.js`
- `website/js/app-runs.js`
- `website/js/app-evidence-map.js`
- `website/js/app-evidence-panels.js`
- `website/js/app-eudr.js`
- `website/js/app-bindings.js`
- `website/js/app-shell.js` (thin composition root)

### Ownership Boundaries

- `app-core-state.js`: single state store + transition helpers.
- `app-core-dom.js`: DOM helpers (`setText`, guarded query helpers, small UI utilities).
- `app-profiles.js`: app registry and app contract resolution (eudr/conservation/portfolio/etc.).
- `app-auth.js`: login/logout, `/.auth/me` bootstrap, auth-dependent UI gating.
- `app-billing.js`: billing status, emulation, capability rendering.
- `app-runs.js`: queue, poll, run history normalization/sorting/selection.
- `app-evidence-map.js`: Leaflet map, frame/layer controls, compare mode, AOI selection visuals.
- `app-evidence-panels.js`: NDVI/weather/change/resource rendering and parcel notes/overrides UI flows.
- `app-eudr.js`: EUDR assessment trigger, usage card, summary export behavior.
- `app-bindings.js`: all `addEventListener` and `bindClick` registrations.
- `app-shell.js`: boot order and dependency wiring only.

### App Contract (Required)

Each app profile must provide:

- `id`: stable app key (`eudr`, `conservation`, `portfolio`, ...)
- `entry`: route/body detection rules
- `labels`: copy and CTA text
- `featureFlags`: enabled capabilities (notes, override, usage card, compare mode, etc.)
- `policy`: app rules (for example: imagery date constraints, export visibility rules)
- `renderHints`: ordering/emphasis of panels and summaries

Shared modules consume this contract and must not hardcode app-specific branching.

## Context Preservation Rules

These rules prevent loss of product context while code is split.

1. Keep current behavior vocabulary intact.

    - Preserve concepts: `workspaceRole`, `workspacePreference`, run phases, evidence mode, EUDR locked mode.

2. Move code with its language and comments.

    - When extracting a function, move nearby constants and labels with it.
    - Do not rewrite wording during extraction unless fixing a bug.

3. Introduce explicit contracts before extraction.

    - Each module gets a small init API and typed input shape comments.
    - Data crossing module boundaries must be normalized in one place.

4. Keep one source of truth for state.

    - No module owns hidden duplicate state for selected run, evidence frame, or auth status.

5. Preserve user-path traces.

    - For each major action (queue run, open evidence, save note, apply override), keep one top-level function name and one status surface message path.

## Execution Plan (Direct, Non-Gradual)

Because this is pre-launch, execute in larger coherent slices instead of tiny migration shims.

### Slice 1: State + DOM foundation

Deliverables:

- create `app-core-state.js` with canonical state object and getters/setters
- create `app-core-dom.js` with null-safe helpers and common UI utilities
- replace direct scattered globals where straightforward

Acceptance:

- no behavior change
- app boots cleanly
- no new console errors

### Slice 2: App profile seam (app-centric split first)

Deliverables:

- create `app-profiles.js` with explicit app contract and profile registry
- resolve active app once at boot
- replace direct app checks in shared logic with profile lookups

Acceptance:

- EUDR/conservation behavior remains unchanged
- app-specific text and toggles come from profile config, not scattered conditionals
- adding a new app does not require editing pipeline lifecycle code

### Slice 3: Run lifecycle extraction

Deliverables:

- move run queue/poll/history/select logic to `app-runs.js`
- keep phase mapping and progress updates together
- isolate cache keys and history normalization in this module

Acceptance:

- queue flow still works end-to-end
- selecting a run still updates URL and UI consistently
- polling stop/resume behavior unchanged

### Slice 4: Evidence domain extraction

Deliverables:

- move map/viewer/frame/layer/compare logic to `app-evidence-map.js`
- move evidence content panels and parcel notes/override workflows to `app-evidence-panels.js`
- keep shared evidence state in core state module

Acceptance:

- frame scrub, RGB/NDVI switching, compare mode, expand/collapse all functional
- AOI selection and reset still synchronize map + side panels

### Slice 5: Auth + billing + EUDR extraction

Deliverables:

- move auth flows to `app-auth.js`
- move billing status/emulation to `app-billing.js`
- move EUDR usage/export/assessment functions to `app-eudr.js`

Acceptance:

- auth gating still controls dashboard and form visibility
- billing panel values and emulation controls remain accurate
- EUDR controls only appear in expected contexts

### Slice 6: Binding and composition cleanup

Deliverables:

- move all click/input listener setup to `app-bindings.js`
- reduce `app-shell.js` to assembly: init state, init modules, bind events, start app

Acceptance:

- `app-shell.js` contains no domain logic
- all modules initialize in deterministic order

## Module Contracts (Initial)

Use explicit namespace exports on `window` to match current no-build setup.

Example pattern:

```javascript
(function(){
  'use strict';

  function init(deps) {
    // validate deps at entry
  }

  window.CanopexRuns = {
    init: init,
    queueAnalysis: queueAnalysis,
    selectRun: selectRun
  };
})();
```

Contract requirements for each module:

- validate required deps and DOM IDs at init
- expose only action methods used by other modules
- keep internal helpers private

Additional contract rule:

- app identity is resolved once and passed in; do not read route/body flags ad hoc across modules.

## Test and Verification Plan

For each slice:

- run focused tests for affected behavior first
- run full suite before merge

Recommended commands:

- `python -m pytest tests/test_frontend_config.py -x -q`
- `python -m pytest tests/test_analysis_submission_endpoints.py -x -q`
- `python -m pytest tests/test_eudr_billing_endpoints.py -x -q`
- `python -m pytest tests/test_export.py -x -q`
- `make test`

Manual smoke checklist each slice:

- sign in/out path
- queue run and observe progress
- switch run from history
- open evidence, scrub frames, toggle RGB/NDVI
- use compare mode and expanded map
- AOI select/reset
- save parcel note
- apply and revert override
- export CSV/PDF/GeoJSON

## Definition of Done

- `app-shell.js` is a thin composition root
- app-specific behavior is isolated behind the app contract/profile layer
- shared pipeline modules are app-agnostic
- each major domain has a dedicated module file
- global mutable state reduced to one shared store
- no duplicate function definitions
- no new console warnings during normal flow
- tests pass and manual smoke checklist passes

## Risks and Mitigations

Risk: Hidden coupling between run and evidence flows.
Mitigation: Keep run->evidence handoff as an explicit contract (`onRunSelected(instanceId)` pattern).

Risk: App behavior leaks back into shared modules.
Mitigation: Enforce app contract boundary and prohibit app-specific conditionals in `app-runs.js` and shared pipeline helpers.

Risk: Future app requires major rewiring.
Mitigation: Maintain two supported deployment shapes (profile model and fully separated app shells) with shared contracts.

Risk: Event binding drift during file moves.
Mitigation: Centralize all bindings in `app-bindings.js` and keep an event map checklist.

Risk: Regressions from moving large functions.
Mitigation: Move code mostly verbatim first, then refactor internals in follow-up commits.

## Workboard Template

Use this checklist in the issue/PR description.

- [x] Extract `app-core-state.js`
- [x] Extract `app-core-dom.js`
- [x] Extract `app-profiles.js`
- [x] Resolve active app via profile contract
- [x] Extract `app-runs.js`
- [x] Extract `app-evidence-map.js` (pure data: pickDefaultLayer, pickInitialFrameIndex, buildNdviTimeseries, latLon)
- [x] `parseCSVCoordinates` moved to `canopex-geo.js`
- [x] Extract `app-eudr.js` (computeCostEstimate; more EUDR functions to follow)
- [x] Extract `app-billing.js` (applyBillingStatus, loadBillingStatus, manageBilling, saveTierEmulation, renderTierEmulation, updateCapabilityFields; init(deps) pattern)
- [x] Extract `app-evidence-panels.js`
- [x] Extract `app-auth.js`
- [x] Extract `app-billing.js`
- [x] Extract `app-eudr.js`
- [x] Extract `app-bindings.js`
- [x] Reduce `app-shell.js` to composition only
- [x] Run focused tests + full `make test`
- [ ] Manual smoke checklist complete

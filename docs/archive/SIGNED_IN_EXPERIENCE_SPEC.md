# Canopex Signed-In Experience Spec

**Date:** 28 March 2026  
**Status:** Proposed replacement for the current logged-in UX

## Summary

The current signed-in experience is not a product surface. It is the public
marketing page with authentication layered on top of the demo.

## Issue Mapping

The signed-in experience work is now mapped onto the GitHub backlog as follows:

- `#312` — authenticated app shell, dashboard home, run history, account area
- `#311` — split signed-in upload flow from demo flow, bulk AOI handling, remove demo-only 25 km guard from the product path
- `#313` — extend the signed-in app surface from single-user scope to team workspace scope

First implementation slice in progress:

- dedicated `/app/` signed-in shell
- post-login redirect from the landing page into `/app/`

That creates three immediate failures:

1. Signing in does not take the user to a dashboard or workspace.
2. Logged-in users still operate through a route and UI explicitly built as a demo.
3. Larger real-world KMLs are blocked by demo-specific guardrails before they ever reach the pipeline.

This document defines what the signed-in experience should be instead.

## Current Reality

### 1. There is no signed-in destination

After authentication, the user returns to the same landing page at `/`.
The current auth state only changes header controls and button labels.

Consequences:

- No dashboard home
- No recent runs
- No saved analyses
- No usage summary
- No account workspace

This matches the roadmap: user dashboard work is still marked as not started.

### 2. The logged-in flow is still the demo

The main signed-in action is still the demo form on the marketing page.
The frontend submit action calls `POST /api/demo-process`, and the backend
route is literally implemented as `demo_process`.

Consequences:

- Users cannot tell whether they are in a sandbox or the real product.
- The primary signed-in workflow inherits demo assumptions and demo copy.
- The product promise and the actual interface are out of sync.

### 3. Pipeline failure is masked by demo fallback behavior

If pipeline submission or orchestration polling fails, the frontend still
launches a direct imagery timelapse fallback so the demo remains visually
useful.

That is acceptable for a public demo, but not for an authenticated product
workflow.

Consequences:

- Users cannot trust whether they are viewing pipeline output or a fallback.
- Failures look like partial success instead of actionable errors.
- Confidence drops immediately after login because the app feels fake.

### 4. Bulk AOI testing is blocked by a demo-specific guard

The frontend enforces `checkPolygonProximity(polygons, 25)` before submission.
That is a demo shaping rule, not a real pipeline capability check.

For `tests/fixtures/medium_50.kml`, the maximum polygon centroid distance from
the group centroid is about `26.3 km`, so the file is rejected client-side.
The first failure is `AOI_48`.

Consequences:

- A realistic multi-AOI test file fails before the backend sees it.
- The signed-in flow contradicts the scaling plan for bulk AOI uploads.
- Users conclude the product cannot handle real workloads.

### 5. Billing exists, but account management does not

There is some logged-in account behavior today:

- billing status lookup
- checkout entry
- customer portal handoff

But these are fragments, not a signed-in workspace. Billing is effectively a
hidden side feature on the marketing page rather than part of a coherent
account area.

## Explicit Answers To The Current Complaints

### Where is my dashboard?

There is no dashboard in the current product surface.

The roadmap already identifies this as the missing item:

- dashboard / saved analyses
- history
- usage stats

### Why do I still see the demo instead of the real pipeline?

Because the current authenticated upload experience is still the demo.

The public site and the signed-in workflow are not separated. Authentication
unlocks the same page instead of transitioning the user into a dedicated app
surface.

### Why does the 50 AOI KML fail?

Because the current frontend applies a 25 km group-centre guard intended for
the demo flow. Your `medium_50.kml` exceeds that threshold slightly, so it is
stopped before real pipeline submission.

## What The Signed-In Experience Should Be

## Product Principle

The public website should sell the product.
The signed-in app should operate the product.

Those are different jobs and should not share the same primary screen.

## Target Information Architecture

### Public Site (`/`)

Purpose:

- explain Canopex
- show a limited demo or sample experience
- handle pricing and conversion
- handle sign-in and sign-up entry

### Authenticated App (`/app`)

Purpose:

- give the user a workspace
- start and monitor real runs
- show saved analyses and exports
- show usage, plan, and billing
- preserve continuity across sessions

## Required Signed-In Screens

### 1. Dashboard Home

The first post-login screen should be a dashboard, not the marketing page.

Minimum content:

- recent runs
- run status summary
- usage remaining / plan summary
- clear primary action: `New Analysis`
- empty state for first-time users

If there are no runs yet, the empty state should still feel like a product
workspace, not a demo prompt.

### 2. New Analysis

This should be the real upload flow for authenticated users.

Capabilities:

- upload KML/KMZ or paste KML text
- parse and summarize before submission
- show feature count and AOI count
- show warnings rather than demo-only rejections where possible
- route to a production-named endpoint, not `demo-process`

The user should understand they are starting a saved, billable, quota-tracked
pipeline run.

### 3. Run Detail Page

Each submission should open a durable run page.

Minimum content:

- run identifier
- submitted time
- runtime status
- pipeline phase progress
- feature/AOI counts
- partial failure counts
- output artifacts
- analysis panels tied to the saved run

This page must survive refresh and revisit.

### 4. Saved Analyses / History

Users must be able to come back later and reopen earlier work.

Minimum content:

- chronological run list
- status badges
- AOI count
- date range / provider summary where available
- links to reopen results

### 5. Account / Billing Area

This can initially be lightweight, but it needs a real home.

Minimum content:

- signed-in identity
- plan and quota state
- billing portal entry
- data retention note
- sign out action

## Demo vs Real Product Rules

### Demo Rules

The public demo may keep stricter limits if needed:

- smaller AOI scope
- fewer polygons
- proximity checks
- fallback imagery mode
- softer reliability guarantees

But those rules must be labeled as demo constraints.

### Product Rules

The signed-in product flow must not silently inherit demo constraints.

Specifically:

- no demo-only 25 km centroid guard on the real upload path
- no fallback-to-demo rendering when a real pipeline run fails
- no `demo` naming in user-facing copy for authenticated work
- no ambiguity about whether the user is running the real pipeline

## How Bulk AOI Uploads Should Work

The scaling plan explicitly calls for bulk AOI processing and 200+ polygon
support. The signed-in UX must reflect that direction.

### Expected behavior for large KMLs

For larger files such as `medium_50.kml`, the app should:

1. Accept the upload into the signed-in pipeline flow.
2. Run preflight analysis and show the user what was detected.
3. Warn about runtime, cost, quota, or batching if necessary.
4. Queue the run instead of rejecting it with a demo-specific proximity rule.

### Preflight summary should include

- number of polygons
- geographic spread
- estimated processing mode (`single run`, `bulk run`, `may batch`)
- likely quota impact
- any hard backend limit that truly applies

## First-Time Signed-In User Journey

The first login should follow this path:

1. User signs in.
2. User lands on `/app`, not `/`.
3. User sees a welcome state with plan, usage, and `New Analysis`.
4. User uploads a KML into the real pipeline flow.
5. User is taken to a run detail page.
6. Completed runs appear in dashboard history automatically.

The current flow skips steps 2, 3, 5, and 6 entirely.

## Returning User Journey

The returning user should be able to:

1. Sign in.
2. See recent runs immediately.
3. Resume or inspect an in-progress run.
4. Reopen an older analysis.
5. Start a new run from the dashboard.
6. Check quota and billing without hunting through the landing page.

## Implementation Priorities

### Priority 1: Separate the surfaces

Create a dedicated authenticated app shell and redirect logged-in users there.

Minimum acceptable first step:

- public marketing page remains at `/`
- authenticated workspace lives at `/app`

### Priority 2: Split demo and production submission paths

The public demo may continue to use demo-specific constraints and naming.
Authenticated users should submit through a real pipeline path.

### Priority 3: Ship a minimal dashboard before the full database migration

The roadmap notes that the full dashboard is blocked on better data storage.
That is true for a rich dashboard, but not for a minimal one.

An MVP signed-in dashboard can still ship using existing blob-backed records:

- recent runs
- usage/quota summary
- billing entry
- reopen latest result

### Priority 4: Remove demo-only guardrails from the signed-in path

The 25 km centroid rule should either:

- remain demo-only, or
- become a warning in the signed-in product flow

It should not block realistic authenticated uploads.

### Priority 5: Stop masking product failures with demo fallback

If a real pipeline run fails, the app should say so clearly.
Fallback imagery can exist, but only if it is explicitly labeled as fallback
preview data and not presented as a successful pipeline result.

## Definition Of Done For The Signed-In UX

The signed-in experience should be considered acceptable only when all of the
following are true:

- signing in routes to a dedicated app surface
- the app has a real dashboard home
- authenticated users do not operate through `demo` copy or routes
- users can revisit prior analyses
- users can see usage and billing in one place
- realistic multi-AOI KMLs are handled by the product flow, not rejected by
  demo-only rules
- pipeline failures are explicit and trustworthy

## Bottom Line

Right now, signing in unlocks the demo.

What it should do is open the product.

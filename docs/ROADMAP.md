# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. The project board holds the live queue.

Last updated: 2026-10-28

---

## Active Work Queue

**Live prioritised board:** [github.com/users/Hardcoreprawn/projects/2](https://github.com/users/Hardcoreprawn/projects/2/views/1)

Use the board for day-to-day prioritisation. Issues are labelled:

- `priority:now` — currently being worked on
- `priority:next` — up next after current work
- `priority:backlog` — ordered, not yet scheduled

**Housekeeping** (bundle with adjacent work, don't schedule separately):
`#573` CSP wildcards · `#593` Pydantic deprecation · `#625` poll_order refactor ·
`#519` self-host Leaflet · `#569` old domain · `#570` ops docs risk · `#584` data model ·
`#525`/`#526` deploy perf · `#252`/`#228` rate limiter/replay (Stage 4) ·
`#402` security-gated production deploys (deferred; partial hardening in PR #711)

---

## Working agreements

**WIP limit — Copilot agent PRs: max 3 open.** No more than 3 open Copilot
agent PRs (drafts + ready) at any time. Finish work before starting more:
promote to ready and merge, or close, before the autopilot assigns new issues.

- Enforced by the backlog autopilot queue cap
  (`AUTOPILOT_MAX_OPEN_AUTOPILOT_PRS=3`, fallback default `3` in
  [scripts/backlog_autopilot.py](../scripts/backlog_autopilot.py) and
  [.github/workflows/backlog-autopilot.yml](../.github/workflows/backlog-autopilot.yml)).
- Scope is agent PRs only — Dependabot and human PRs are not counted.
- When the cap is hit, drain first: a coding-agent draft whose Watchdog says
  `READY_TO_PROMOTE` is actionable — `gh pr ready <n>` then review/merge; close
  dead or superseded drafts. Do not raise the cap to unblock; clear the queue.

**Definition of Done (agent PRs).** A PR is *finished* only when it links a
closing issue (`Closes #NNN`), adds tests for any new behaviour, is green on
`make check`, is marked ready (not draft), and reports its Watchdog status.
Anything short of this is *started, not finished*. See
[.github/copilot-instructions.md](../.github/copilot-instructions.md)
"Delivery Workflow".

**Completion SLA — 5 days.** A draft agent PR with an implementation blocker
(failing checks, unresolved review threads, or a missing linked issue) and no
progress for more than 5 days may be closed and re-queued. Missing CI or review
state alone never triggers stale closure. Enforced by the PR Watchdog stale-close
path (opt-in via `AUTOPILOT_WATCHDOG_STALE_CLOSE`; off until the maintainer
enables it).

---

## Direction

**EUDR compliance is the product.** Conservation monitoring is mothballed
until EUDR reaches revenue.

- **Landing page** (`/`) — positions Canopex as a geospatial platform,
  directs users to the EUDR app.
- **EUDR app** (`/eudr/`) — 2 free trial parcels → £49/month base +
  £3/parcel metered overage (graduated volume tiers). Billing is per-org.
- **Platform apps** (`/account/`) — shared concerns: account management,
  billing, org settings. Usable by all vertical apps.
- **Conservation** (`/app/`) — code stays, no new development or promotion.
- Master tracker: #606.

**Multi-app platform architecture:** The satellite pipeline (acquisition,
NDVI, change detection, enrichment) is shared infrastructure. Each product
vertical (EUDR, conservation, agriculture) gets its own URL namespace and
entry page. `/eudr/` ships first; others follow when EUDR reaches revenue.

**Backend:** Split Container Apps Function Apps — slim orchestrator ingress
and heavy compute workers. Browser clients must target orchestrator hostname
only (`/api-config.json`), while compute hosts activity-heavy execution.
Container Apps Jobs (#467) stay deferred — confirmed by cost analysis (2026-05):
both FAs are on the Consumption plan with alwaysReady=0, so idle cost is already
£0. CAJ would add complexity without reducing cost. Revisit when sustained user
load makes the per-invocation billing model a disadvantage vs a dedicated worker.

**Build rules (keep dev easy):**

- New browser/API features must integrate at orchestrator ingress only.
- Compute host must not be referenced by frontend config, links, or product-facing docs.
- Event Grid subscription endpoint ownership is orchestrator-only.
- Shared registration/auth modules are preferred over duplicating route wiring.
- Any deploy change touching app settings or hostnames needs a drift-guard test.

**Execution order:** 2C → 2D → 2E → 2F → 2G → 3A → 3B → 3B.5 → 3C → 3 → 4 → 5.
Stages 2D and 2E can proceed in parallel. Stage 3B.5 is next priority after 3B.

**Policy-watch gate (EUDR amendments):** Treat Parliament/Council alignment notices as directional only.
Before shipping compliance-interpretation changes, revalidate assumptions against final trilogue text,
published legal acts, and latest Commission implementation guidance.

**Value focus while rules evolve:** Prioritise low-regret capabilities that remain useful under both
strict and simplified obligations: evidence provenance, reproducible exports, audit trails, and
portfolio-level risk visibility.

---

## Recently Landed

| PR | Summary |
|----|---------|
| #1614 | Reconciled the merge/review ledger and verified Project synchronization (closes #1613). Documentation only; release acceptance remains separate. |
| #1617 | Added local ownership prerequisites for real acquisition/export proof (closes #1616). Two real fixtures and all six exports passed; production auth and ownership gates unchanged. |
| #1612 | Preserved unavailable and sampled EUDR evidence in UI/PDF output (closes #1588). Local browser/PDF checks and hosted integration/Pipeline e2e passed; scientific acceptance remains separate. |
| #1607 | Restored advisory Infracost estimates without Azure login or remote state (closes #1606). Hosted breakdown, artifact and comment publication verified; partial configuration estimate, not a billing forecast. |
| #1610 | Updated fpdf2 to 2.8.8 for the reported resource-access and SVG-expansion advisories. Required CI passed; no open Dependabot alerts at the post-merge check. |
| #1609 | Documented Function App update ownership, identity-response history and restart risks (closes #1608). Documentation only; no ownership migration or freeze change. |
| —  | **MILESTONE (2026-07-12): Domain-model overhaul begun — Organisation as the single ownership root** (epic #1057; model documented in `docs/DATA_MODEL.md` — conceptual/logical/physical + D1–D5 divergences). **D3 landed**: per-user quota retired, org pool is the sole accounting unit. D1 (auth active-org resolution) in progress; D2 (org-partitioning) sequenced after D1. |
| —  | **MILESTONE (2026-05-20): First confirmed end-to-end pipeline run in production.** KML upload → blob trigger → orchestrator → imagery acquisition → NDVI + change detection + climate enrichment → results rendered in dashboard. Mean NDVI, range, trajectory, 54-frame timelapse, and EUDR compliance entry point all returned correctly. Stage 2C proof-of-life confirmed. |

**Return-to-live status:** `DEPLOY_PAUSED=true`; these code merges do not
certify a live release. #1013 retains the release acceptance ledger, including
real-data proof (#1379), scientific/native validation (#1223, #1521), and
deployed golden-journey evidence (#708). Truthful evidence presentation (#1588)
is merged in #1612; explicit compute-resource deployment handling (#884)
remains unmerged.
Infracost #1604 and repair #1607 are merged; #1607's hosted setup,
breakdown, artifact retention and PR-comment publication were verified.
The geometry/sensor review ledger #1583 is closed after verified merge gates
and owner-authorized Project synchronization (480 items, zero order mismatches).
The #1617 candidate completed both real cattle/coffee fixtures and all six
format-valid exports after local ownership setup. This clears the observed
mechanical acquisition/export failure, not human/scientific acceptance
of #1379; incident #1615 remains a separate follow-up. The six new manual AOIs
in #1618 have not yet had full pipeline or human imagery validation. Five open
code-scanning findings are tracked separately in #1213, #1214 and #1611;
a green scanner run is not dismissal of those findings.

---

## Stage status

- **Stage 2C (Pipeline Verification & User Journey):** Complete
- **Stage 2D (Revenue Enablement):** Complete
- **Stage 2E (Release Safety):** Complete
- **Stage 3 (Growth & Retention):** In Progress

---

## Per-stage issue tables

See the [live board](https://github.com/users/Hardcoreprawn/projects/2) for up-to-date execution order and status. Each issue is labelled with its stage and priority.

---

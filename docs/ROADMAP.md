# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. The project board holds the live queue.

Last updated: 2026-08-14

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
| #1398 | fix(pipeline): `_read_submission_ticket` silently skipped ticket enrichment (`user_id`/`tier`/`eudr_mode`) for any container-root blob upload (bare filename, no subfolder) — the exact pattern used by `scripts/simulate_upload.py` and `scripts/corpus_runner.py`. Found via local hand-testing against real Planetary Computer data (closes #1396). |
| #1391 | feat(eudr): HS/CN commodity reference data (`treesight/eudr_commodities.py`) for all 7 EUDR commodities, verified against the consolidated Regulation (EU) 2023/1115 text, plus a new `eudr-dds` export format producing an Annex-II-structured draft due diligence statement (closes #1384). |
| #1373 | fix(deploy): enforce dev/prd custom-domain ownership preflight (closes #1330) — new `scripts/validate_domain_ownership.py` preflight guard + `allow_domain_transfer` workflow_dispatch gate. **Note:** this PR also shipped an untracked Infracost workflow resilience fix (`continue-on-error` on transient Azure/Tofu-init failures) bundled in by the coding agent to unblock its own CI — retroactively tracked as #1394; no runtime issue, but a reminder to keep PRs single-purpose. |
| #1378 | chore: remove dead scratch file (`LOG_TARGETS.json`, previously leaked real Azure resource IDs before being emptied but never deleted), archive 6 stale dated review docs into `docs/archive/` per existing convention (closes #1377). |
| #1388 | docs(eudr): add TraceX competitive comparison (`PERSONA_DEEP_DIVE.md` §8.8) — confirms EU TRACES NT is live (not blocked) with a 30 Dec 2026 deadline for large/medium operators; reprioritizes the formal DDS-template gap from Low to Medium; spawns #1384 (DDS export), #1385/#1386 (watch items: direct TRACES submission, ERP integration) (closes #1387). |
| #1376 | feat: add `pytest-timeout` to dev deps with 60s default timeout, so import-time stalls/hangs fail fast with a clear signal instead of silently wasting CI minutes (closes #1119). |
| —  | **MILESTONE (2026-07-12): Domain-model overhaul begun — Organisation as the single ownership root** (epic #1057; model documented in `docs/DATA_MODEL.md` — conceptual/logical/physical + D1–D5 divergences). **D3 landed**: per-user quota retired, org pool is the sole accounting unit. D1 (auth active-org resolution) in progress; D2 (org-partitioning) sequenced after D1. |
| —  | **MILESTONE (2026-05-20): First confirmed end-to-end pipeline run in production.** KML upload → blob trigger → orchestrator → imagery acquisition → NDVI + change detection + climate enrichment → results rendered in dashboard. Mean NDVI, range, trajectory, 54-frame timelapse, and EUDR compliance entry point all returned correctly. Stage 2C proof-of-life confirmed. |

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

# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. The project board holds the live queue.

Last updated: 2026-07-12

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

**Completion SLA — 5 days.** An agent PR that stays `BLOCKED` or stale (no
progress) for more than 5 days is closed and its linked issue re-queued, so the
queue keeps moving instead of accreting half-done work. Enforced by the PR
Watchdog stale-close path (opt-in via `AUTOPILOT_WATCHDOG_STALE_CLOSE`; off until
the maintainer enables it).

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
| #1109 | chore(harness): finish linked-issue enforcement — registered the `check-issue-link` job (from `require-linked-issue.yml`) as a required status check on `main`, completing the gate whose workflow + PR template already shipped; backfill was a no-op (only open PR already linked) (closes #945). |
| #1107 | chore(security): retire the demo valet/artifact/CORS-proxy surface — deleted `blueprints/demo.py` and its `/api/demo-valet-tokens`, `/api/demo-artifacts`, `/api/proxy` routes; de-registered the demo blueprint from compute; removed the orphaned `proxy_limiter`; SSRF bypass coverage retargeted to the shared `host_in_allowlist` primitive; API docs/OpenAPI/SYSTEM_SPEC updated; regression guard added (closes #922, supersedes interim hardening PR #919). |
| —  | **MILESTONE (2026-07-12): Domain-model overhaul begun — Organisation as the single ownership root** (epic #1057; model documented in `docs/DATA_MODEL.md` — conceptual/logical/physical + D1–D5 divergences). **D3 landed**: per-user quota retired, org pool is the sole accounting unit. D1 (auth active-org resolution) in progress; D2 (org-partitioning) sequenced after D1. |
| #893 | chore(recovery): verify EUDR per-parcel metered Stripe billing recovery from `feat/eudr-metered-billing` — confirmed work already incorporated via PR #657; current codebase is an evolved superset with org-pooled accounting, graduated overage tiers, and emulated-subscription support (closes #893). |
| #1093 | chore: add `make prune-branches` for local branch hygiene — deletes local branches whose upstream is `[gone]` after PR merges (closes #1092). |
| #1075 | fix(web): eliminate CSP-blocked inline script on `/eudr/` — subscribe-modal + billing-bridge logic moved to first-party `website/js/app-eudr-subscribe-modal.js`; regression guards against reintroducing inline executable script (closes #773). |
| #1089 | chore(harness): migrate remaining `pip` usages to `uv`/`uvx` — `detect-secrets` (security.yml) and infracost metrics collection now run via `uv`; script/runtime prereq hints updated (ADR 0005 execution model, epic #1082, closes #1084). |
| #1088 | docs: ADR 0005 — consolidate onto a single containerised dev + CI path; standardise on `uv` (execution-context rule, dev image extends `treesight-base` consumed by digest, lock-vs-image guard). Delivery tracked by epic #1082 (closes #1083). |
| #1059 | feat(billing): retire legacy per-user quota — org pool (`reserve_run`/`finalize_run`) is the sole accounting unit; billing-status + free/overage readers migrated to org usage; `quota.py` deleted (D3, closes #1055). |
| #1068 | fix(autopilot): dependency-aware, no-duplicate dispatch — skip issues that are `blocked`, declare an open `blocked by`/`depends on`, or already have an open linked PR; add issue template capturing dependencies/persona/acceptance (closes #1067). |
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

# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. The project board holds the live queue.

Last updated: 2026-08-06

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
| #1267 | feat(test): 200+ AOI scale gate — `tests/test_monster_aoi_scale.py` proves the Stage 2 exit criterion ("200+ concurrent AOIs process reliably without OOM or timeout") as a standard `make check` gate; parse-level + mocked fan-out assertions plus an integration-marked connectivity guard; baseline documented in `docs/scale_baseline.md` (closes #437). |
| #1266 | feat(pipeline): pipeline run telemetry — every successful run writes a lightweight stats document (AOI count/area/spread, enrichment set, duration, tier) to a `pipeline_stats` Cosmos container, seeding training data for the future Pipeline ETA estimator (#399) (closes #400). |
| #1275 | feat(dev): relay Azurite blob uploads to func as synthetic Event Grid events — `scripts/dev_event_grid_relay.py` + new compose service makes a real KML upload complete the full pipeline end-to-end in local dev for the first time (closes #1273). |
| #1274 | fix(dev): stand up the Cosmos DB Emulator for `make dev-all` — gated `COSMOS_KEY` local-auth path (production untouched, verified by an infra-scanning test) gives local dev working org/user/billing persistence for the first time (closes #1269). |
| #1221 | refactor(pipeline): explicit activity-output contracts at orchestrator ingestion seams — replaced 6 unchecked `cast()` calls (`parse_kml`, `load_offloaded_features`, `prepare_aoi`/`write_metadata` fan-out, `store_aoi_claims`) with runtime contract checks (`treesight/pipeline/contracts.py`) that fail fast with a clear error on malformed Durable activity output instead of surfacing a deep `KeyError` (closes #795). |
| #1220 | fix(auth): heal org membership when CIAM auth subject changes — users whose `oid` changes between sign-ins (e.g. LocalAccount → federated MicrosoftAccount merge) now retain access to their org via verified-email lookup instead of silently landing in a fresh free-tier personal org; case-insensitive Cosmos email matching fixed post-review (closes #742). |
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

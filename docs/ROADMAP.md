# Canopex — Roadmap

**Single source of truth for what to build next.**
Issues hold the detail. The project board holds the live queue.

Last updated: 2026-05-21

---

## Board-driven execution order

- **Work top-to-bottom from the [live board](https://github.com/users/Hardcoreprawn/projects/2).**
- `priority:now` = current focus; `priority:next` = queue; `priority:backlog` = ordered but unscheduled.
- Update this file's "Recently Landed" table and the board when PRs merge or stage status changes.

---

## Recently Landed

| Date       | PR   | Issue(s) | Description                                      |
|------------|------|----------|--------------------------------------------------|
| 2026-05-21 | [#873](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/pull/873) | #—       | chore: board-based prioritisation + pipeline regression guards |
| 2026-05-21 | [#874](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/pull/874) | #863     | fix(pipeline): parallelise per-AOI enrichment loop |
| 2026-05-20 | #848 | #403     | feat(rollout): generalised feature flag evaluator (phase 1) |
| 2026-05-20 | #763 | #708     | fix(release): full e2e production smoke gate as promotion blocker |
| 2026-05-20 | #762 | #756, #757, #759, #760 | fix(auth/ops): CIAM, token lifecycle, concurrency cap, health endpoint |
| 2026-05-20 | #744 | #710     | feat(auth): frontend CIAM token flow with MSAL (Option B phase 2) |
| 2026-05-20 | #736 | #729–#734| fix: EUDR pipeline edge cases (Stage 2E.5)        |
| 2026-05-20 | #535 | #535     | fix: live Stripe billing flow verification on production |

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

# Canopex Copilot Instructions

## Source Of Truth

- Treat `docs/ROADMAP.md` as the stage and direction source of truth. Day-to-day work ordering lives on the [GitHub Project board](https://github.com/users/Hardcoreprawn/projects/2) (`priority:now` → `priority:next` → `priority:backlog`).
- Treat `docs/PERSONA_DEEP_DIVE.md` as the source of truth for conservation, ESG/EUDR, and agricultural-advisor needs.
- Use `docs/PID.md` for product scope and system intent.
- Use `docs/ARCHITECTURE_OVERVIEW.md`, `docs/API_INTERFACE_REFERENCE.md`, and `docs/OPERATIONS_RUNBOOK.md` when changing runtime behavior, contracts, or operations.

## Prioritization

Prioritise work in this order:

1. **`priority:now` issues** — these are the current focus. See the live board: [github.com/users/Hardcoreprawn/projects/2](https://github.com/users/Hardcoreprawn/projects/2). Issues labelled `priority:next` form the queue; `priority:backlog` is ordered but unscheduled.
2. **Stabilise auth, billing, and security** — Stage 2C is complete (2026-05-20). Do not open Stage 3 growth features until auth, billing, and security gates are solid.
3. **Thin vertical slices** — prefer one stage at a time over broad refactors that touch multiple stages at once.
4. **Defer infrastructure optimisation** (T2/T3 split, Container Apps Jobs) until monthly active users exceed 1,000 or monthly revenue exceeds £5,000.

For every substantial task, identify the primary persona, the job-to-be-done being improved, and the acceptance signal.

## Delivery Workflow

- Always start new work on a clean branch from `main`. Before creating the branch, verify the working tree is clean (`git status`). Do not pile unrelated changes onto an existing feature branch.
- **Every PR must close at least one GitHub issue.** Prefer exactly one issue per PR. If no issue exists for the work, create one before opening the PR. Put the link in the PR body's **Linked issue** section as `Closes #NNN` (or `fixes`/`resolves`) — a machine-readable reference, **not** prose like "Issue #NNN tracks this". The `require-linked-issue` gate and the PR Watchdog both check for this exact pattern; a bare `#NNN` mention does not count and will block the PR.
- **Do not leave a finished PR in draft.** Once the work is complete and the PR Watchdog reports `READY_TO_PROMOTE` / `READY_FOR_MAINTAINER_REVIEW`, mark it ready (`gh pr ready`). Draft PRs do not run full CI, so a completed draft stalls with zero validation.
- Start planned work from a GitHub issue whenever practical. Apply the appropriate `priority:*` label to new issues.
- Keep pull requests narrow, stage-aligned, and traceable to a roadmap item or issue.
- Update `docs/ROADMAP.md` "Recently Landed" table and the GitHub Project board when PRs merge or stage status changes.
- When behavior, contracts, or rollout expectations change, update the relevant tests and docs in the same change.

## Backlog Hygiene

- When manipulating GitHub Issues or Projects, always fetch the full dataset explicitly. For CLI operations, pass a `--limit` large enough to cover the whole board; never rely on defaults.
- When reordering a GitHub Project, verify the exact final order against the intended full ordered set and report the mismatch count. Do not stop at checking only the top items.
- If a dependency is discovered (`blocked by`, `depends on`, stage ordering, prerequisite architecture work), link the issues in GitHub and reorder the board in the same task.
- For staged issues with numbered prefixes (for example `2E.5.1`, `2E.5.2`), preserve ascending execution order unless an issue body or roadmap note explicitly states a different dependency.
- Never mark issues as duplicate or superseded from title similarity or keyword overlap alone. Require explicit scope containment, linked acceptance criteria, or a clear umbrella/child relationship.
- Prefer umbrella issue plus child slices over multiple overlapping top-level issues. When a broader tracker already exists, attach narrower work to it instead of creating another peer issue.
- Default to `link and conditionally close later` when overlap is plausible but not certain. Only close immediately when duplication is unambiguous.
- Consolidation guidance must be directional. Do not post symmetrical `A may replace B` and `B may replace A` claims.
- For GitHub Project GraphQL reordering, omit `afterId` entirely for the first item. Do not send empty or null node IDs.
- Before posting dependency or consolidation comments, check for an existing equivalent comment and skip duplicates.
- Backlog simplification is part of planning work. When asked to plan or prioritise, identify blockers, umbrellas, child slices, and likely covered follow-on work so the backlog stays executable rather than merely sorted.

## Release Safety

- For deploy, infra, auth, billing, and rollout work, prefer build-once/promote semantics and avoid accidental PR-branch deploys to shared environments.
- Treat readiness checks, post-deploy smoke, structured logging, and rollback paths as part of the feature, not follow-up work.
- Do not weaken quota, auth, billing, or security gates just to make a change pass.

## Persona Lens

- Conservation work should reduce time from AOI upload to usable evidence or monitoring action.
- ESG/EUDR work should improve auditability, reproducibility, or compliance confidence.
- Agriculture work should improve batch parcel handling, defensible decisions, or export usability.
- Keep the product usable for non-GIS operators. KML/KMZ remains a first-class input, not a temporary workaround.

## Validation

- Write the test first. The test defines the contract; the implementation makes it pass.
- Run the narrowest meaningful executable validation first.
- Prefer behavior-scoped tests over broad suite runs when iterating.
- For cross-cutting, deploy, auth, billing, API, or runtime changes, run the `Code Review Critic` after local validation and before requesting PR review.
- Call out residual rollout risk when runtime validation is unavailable.

---

## Recently Landed

- [#873](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/pull/873): board-based prioritisation + pipeline regression guards
- [#874](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/pull/874): parallelise per-AOI enrichment loop ([#863](https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite/issues/863)) — prevent activity timeout at 50+ AOIs (ThreadPoolExecutor, concurrency cap, error isolation, tests, TDD)

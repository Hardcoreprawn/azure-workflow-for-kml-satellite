# Canopex Copilot Instructions

## Source Of Truth

- Treat `docs/ROADMAP.md` as the order-of-work source of truth.
- Treat `docs/PERSONA_DEEP_DIVE.md` as the source of truth for conservation, ESG/EUDR, and agricultural-advisor needs.
- Use `docs/PID.md` for product scope and system intent.
- Use `docs/ARCHITECTURE_OVERVIEW.md`, `docs/API_INTERFACE_REFERENCE.md`, and `docs/OPERATIONS_RUNBOOK.md` when changing runtime behavior, contracts, or operations.

## Prioritization

- **Stage 2C (Pipeline Verification & User Journey) is the current priority.** Do not open Stage 3+ work until the minimum viable user journey works end-to-end in Azure.
- Finish Stage 2D (Revenue Enablement) and Stage 2E (Release Safety) before Stage 3 growth features.
- For every substantial task, identify the primary persona, the job-to-be-done being improved, and the acceptance signal.
- Prefer thin vertical slices over broad refactors that move several roadmap stages at once.
- Do not spend engineering time on infrastructure optimisation (T2/T3 split, Container Apps Jobs) until user volume or revenue justifies it.

## Delivery Workflow

- Always start new work on a clean branch from `main`. Before creating the branch, verify the working tree is clean (`git status`). Do not pile unrelated changes onto an existing feature branch.
- Start planned work from a GitHub issue whenever practical.
- Keep pull requests narrow, stage-aligned, and traceable to a roadmap item or issue.
- Update `docs/ROADMAP.md` when PR state, stage status, or milestone status changes.
- When behavior, contracts, or rollout expectations change, update the relevant tests and docs in the same change.

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

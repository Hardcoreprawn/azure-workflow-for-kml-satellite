---
name: roadmap-execution
description: 'Use for roadmap items, product overhauls, stage planning, issue execution briefs, or persona-led delivery planning. Runs the Canopex workflow from roadmap slice to persona audit, release gate, docs drift, implementation plan, and PR readiness.'
argument-hint: 'Roadmap item, issue number, or overhaul target'
user-invocable: true
---

# Roadmap Execution

Use this skill when you need one repeatable workflow for turning a roadmap item or overhaul target into an execution-ready slice.

## When To Use

- A roadmap item needs to be turned into an issue brief
- A large capability needs to be broken into thin vertical slices
- A proposed change needs persona, release-safety, and docs-drift checks before implementation
- You want a consistent workflow for moving from planning to PR readiness

## Procedure

1. Read the source-of-truth docs first:
   - `docs/ROADMAP.md`
   - `docs/PERSONA_DEEP_DIVE.md`
   - `docs/PID.md`
   - `docs/ARCHITECTURE_OVERVIEW.md`
2. Fill the [execution brief template](./assets/execution-brief-template.md).
3. Run `Architect` or `/Roadmap Slice` to produce the smallest ordered slices.
4. Run `Delivery` or `/Persona Gap Audit` to verify measurable persona/JTBD value.
5. If the work touches deployment, runtime config, auth, billing, or rollout, include the `/Release Gate Audit` criteria in one `Hamilton` pass.
6. If the work changes public behavior, contracts, operations, or status, include `/Docs Drift Audit` criteria in that same `Hamilton` pass rather than launching another reviewer. For a bounded packet review, use `Council`; stop on blockers or budget exhaustion. Single-role briefs do not require a full council.
7. Only then implement the smallest slice that can be validated narrowly.
8. Before PR merge, ensure the affected contract/operational docs and tests are updated and request Copilot review. Update the roadmap or GitHub Project board only when explicitly requested; neither is a per-merge requirement.

## Stage Gates

- Use the [persona and stage gates](./references/persona-and-stage-gates.md) to decide whether the slice should proceed now or wait for Stage 2A completion.
- Do not open broad Stage 3 or Stage 4 implementation while Stage 2A release-safety work remains materially incomplete, unless the user explicitly overrides that sequencing.

## Output Expectations

- Named persona and JTBD
- Ordered thin slices
- Validation gates
- Rollout and docs gates
- Explicit next action

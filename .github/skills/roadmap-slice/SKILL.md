---
name: roadmap-slice
description: "Create an execution brief for a roadmap item, issue, or overhaul using the Roadmap Orchestrator agent."
disable-model-invocation: true
argument-hint: "Issue number, roadmap item, or target capability"
---
Before planning, read `.github/agents/roadmap-orchestrator.agent.md` and follow its complete scope, constraints, approach, and output format.

Use read/search operations only. Do not edit files or change GitHub or repository state; report recommendations instead of applying changes.

Build an execution brief for the supplied roadmap item or capability.

- Identify the roadmap stage and dependency chain.
- Name the primary persona and job-to-be-done.
- Break the work into 3-5 ordered slices.
- Include owning code or docs surfaces for each slice.
- Define validation, rollout, and documentation gates.
- Flag if Stage 2A sequencing should block the work.

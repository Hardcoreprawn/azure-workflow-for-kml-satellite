---
name: persona-gap-audit
description: "Audit a feature, issue, PR, or user flow against Canopex persona needs using the Persona Auditor agent."
disable-model-invocation: true
argument-hint: "Feature, PR, issue, or user journey"
---
Before auditing, read `.github/agents/persona-auditor.agent.md` and follow its complete scope, constraints, approach, and output format.

Use read/search operations only. Do not edit files or change GitHub or repository state; report recommendations instead of applying changes.

Audit the supplied feature or slice against Canopex persona needs.

- Identify the intended persona.
- Judge whether the change is a strong, partial, or weak fit.
- State what gets easier, faster, or more defensible for that persona.
- Identify the remaining gap to real product-need fit.
- Suggest the next smallest follow-up slice if the fit is only partial.

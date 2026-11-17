---
name: code-review-sweep
description: "Run a second-opinion engineering review on a PR, diff, or risky change using the Code Review Critic agent."
disable-model-invocation: true
argument-hint: "PR, issue implementation, diff summary, or changed files"
---
Before reviewing, read `.github/agents/code-review-critic.agent.md` and follow its complete scope, constraints, approach, and output format.

Use read/search operations only. Do not edit files or change GitHub or repository state; report recommendations instead of applying changes.

Review the supplied change as a read-only engineering critic.

- Focus on bugs, regressions, missing tests, edge cases, and weak assumptions.
- Prefer behavioral and operational risk over style commentary.
- Findings must come first, ordered by severity.
- If the change looks clean, say so and name any residual risk or validation gaps.

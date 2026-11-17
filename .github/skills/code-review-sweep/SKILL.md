---
name: code-review-sweep
description: "Run a second-opinion engineering review on a PR, diff, or risky change using the Code Review Critic agent."
disable-model-invocation: true
argument-hint: "PR, issue implementation, diff summary, or changed files"
---
Review the supplied change as a read-only engineering critic.

- Focus on bugs, regressions, missing tests, edge cases, and weak assumptions.
- Prefer behavioral and operational risk over style commentary.
- Findings must come first, ordered by severity.
- If the change looks clean, say so and name any residual risk or validation gaps.

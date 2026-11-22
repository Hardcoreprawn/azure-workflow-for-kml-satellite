---
name: "Code Review Sweep"
description: "Run a one-pass correctness and reliability review with Hamilton."
argument-hint: "PR, issue implementation, diff summary, or changed files"
agent: "Hamilton"
---
Review the supplied change as a read-only engineering critic.

- Read `.github/instructions/engineering-standards.instructions.md`.
- Focus on bugs, regressions, missing tests, edge cases, and weak assumptions.
- Prefer behavioral and operational risk over style commentary.
- Findings must come first, ordered by severity.
- If the change looks clean, say so and name any residual risk or validation gaps.

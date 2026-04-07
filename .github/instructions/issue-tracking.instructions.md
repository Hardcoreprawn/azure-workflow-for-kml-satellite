---
description: "Standing orders for tracking discovered issues, deprecations, test flakes, and tech debt during any task."
name: "Issue Tracking Discipline"
applyTo: "**"
---
# Issue Tracking Discipline

## When you find something broken that isn't the current task

If you encounter any of the following while working on an unrelated task, **do not fix it inline**. Instead:

1. Check if a GitHub issue already exists (search by keyword).
2. If no issue exists, create one with:
   - Clear title: `[discovered] <short description>`
   - Label: `discovered`
   - Body: what you saw, where, and a minimal repro or pointer
3. Note the issue number in your commit message or PR body under a "Discovered issues" section.
4. Continue with your current task.

### What counts as "discovered"

- **Test failures** not caused by your change
- **Deprecation warnings** from dependencies (e.g. `DeprecationWarning` in test output)
- **Security alerts** you notice in CI output (CodeQL, Trivy, Semgrep, pip-audit)
- **Type errors** or linter warnings in files you didn't modify
- **Runtime warnings** in logs (e.g. missing env vars, fallback paths taken)
- **Dead code** or unused imports in files you're reading
- **Missing tests** for behaviour you're relying on
- **Documentation** that contradicts what the code does

### What does NOT need an issue

- Formatting / whitespace — just fix it with `ruff format`
- Obvious typos in files you're already editing — fix inline
- Import sorting — handled by ruff automatically

## When a PR merges

After any PR merges:

1. Update `docs/ROADMAP.md` → "Recently Landed" table (add your PR, remove oldest if >6 entries).
2. Mark the corresponding stage item as ✅ with the PR number.
3. If the PR closes an issue, verify the issue auto-closed on GitHub.

## Context management

- Reference issue numbers (`#437`), not full descriptions, in roadmap tables.
- The issue holds the detail; the roadmap holds the order.
- Keep PR descriptions linked to issues (`fixes #NNN`) so they auto-close.
- When creating issues for future work, keep scope to one PR. If it's bigger, break it into sub-issues.

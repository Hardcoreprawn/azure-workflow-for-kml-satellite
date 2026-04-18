---
description: "Standing orders for verification, validation, and regression prevention across all PRs. Enforces that main stays working and nothing merges without proof."
name: "Verification & Validation Discipline"
applyTo: "**"
---
# Verification & Validation Discipline

`main` is the deployable branch. It must always work. Every merge is a
potential deployment. These rules prevent regressions.

## Before opening a PR

1. **Run the full test suite locally.** `make test` must pass with zero
   failures. No exceptions, no "it's just a docs change" shortcuts — docs
   changes can break test assertions on route tables or config.
2. **Run lint and format checks.** `ruff check` and `ruff format --check`
   must be clean before committing. Fix issues proactively; do not rely
   on CI to catch them.
3. **Verify affected behavior manually** when the change touches API
   endpoints, UI flows, or pipeline logic. If it's testable locally
   (Azurite, `func start`), test it locally.
4. **Check for regressions in adjacent areas.** If you changed billing
   logic, run billing tests. If you changed parsers, run parser tests.
   If you're unsure what's adjacent, run the full suite.

## CI must pass before merge

- All GitHub Actions checks (lint, test, security scanners) must pass.
- If a scanner flags a finding, fix it — do not dismiss without
  justification and user approval.
- If CI fails on something unrelated to your change, log a `[discovered]`
  issue and get the PR green before merging.

## Review gate

- Every PR must be reviewed before merge.
- Address all review comments. Do not merge with unresolved threads.
- After addressing comments, re-run the test suite to confirm fixes
  didn't introduce new issues.

## After merge

- Verify the merge commit is clean (`git log --oneline -1`).
- If the change affects deployed behavior, check the deployment
  (health endpoint, smoke test, or manual verification as appropriate).
- Finalize `docs/ROADMAP.md` at merge-time / immediately after merge:
  update "Recently Landed", mark the shipped stage items, and close the
  loop. If the PR included roadmap edits, treat them as candidate updates
  to be confirmed or adjusted once the merge is complete.

## Regression prevention principles

- **Tests are the contract.** If behavior isn't tested, it isn't
  guaranteed. When you rely on a behavior, write a test for it.
- **Never weaken a test to make a change pass.** If a test fails, either
  your change has a bug or the test needs updating because the contract
  genuinely changed. Both cases require deliberate thought.
- **Security, auth, billing, and quota gates are load-bearing.** Changes
  to these areas need extra scrutiny. Run the specific test suites
  (`test_auth.py`, `test_billing.py`, `test_hmac_auth.py`) and confirm
  no gate was weakened.
- **Snapshot the working state.** When the app reaches a known-good
  milestone (e.g. "pipeline works end-to-end"), note it in the roadmap.
  Future changes that break that milestone are regressions.
- **Prefer additive changes.** Add new behavior; deprecate old behavior
  with a migration path. Avoid big-bang rewrites that invalidate the
  existing test suite.

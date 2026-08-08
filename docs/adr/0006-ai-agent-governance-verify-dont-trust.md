# ADR 0006: AI Agent Governance — Verify, Don't Trust

## Status

Accepted

## Context

The app previously reached a state where it "mostly worked" but was flaky and
broke on some axis with nearly every change. Deploys "succeeded" while the
live app was unusable. That state was reached gradually, through a
recognisable pattern, not a single incident. Before re-enabling live
deployment or increasing reliance on AI coding agents, that pattern needs to
be named explicitly and closed off mechanically — not just avoided by
intention.

### The failure pattern, with evidence from this repo's own history

**1. Gates that looked like gates but weren't.**
A check existing and a check *enforcing* anything are different things, and
the gap between them is invisible until it's exploited:

- `diff-cover` changed-lines coverage ran in CI for weeks in report-only mode
  — the failing case was permanently swallowed with `|| true` (#1042). An
  agent (or a human) could ship uncovered runtime code and CI stayed green.
- The base-image "no suppressions" Trivy scan passed `ignorefile: ""`
  intending to disable CVE filtering, but GitHub Actions composite actions do
  not reliably let an empty string override a declared default — the scan
  silently used `.trivyignore` anyway. The automated reconciler read that
  filtered result, concluded the suppressed CVEs were resolved, and
  **auto-deleted the security exceptions that were still needed** (#1169).
- `#1013`'s own founding diagnosis: **no gate ever asserted the golden
  journey against the live environment.** The only live check was an
  anonymous HTTP-200 probe against the static site, not the API — a deploy
  could report success while the authenticated upload → orchestrate →
  artifact journey was completely broken.

**2. Silent duplication of core logic.**
Divergent copies of the same calculation are individually plausible in
review and only reveal themselves as a bug in production, if ever:

- Haversine distance was implemented independently three times
  (`treesight/geo.py`, `treesight/pipeline/telemetry.py`,
  `treesight/pipeline/enrichment/runner.py`) before being partially
  consolidated (#1266's review round).
- `_centroid()` exists twice with **incompatible coordinate order** —
  `treesight/geo.py` returns `[lon, lat]`; `treesight/pipeline/enrichment/runner.py`
  has its own copy returning `(lat, lon)` (#1281). A caller that imports the
  wrong one gets swapped coordinates with no type error to catch it.

**3. Backlog state that lies.**
Issue metadata is a control surface for what agents get assigned next — stale
metadata misdirects that control surface, silently:

- Issues "assigned" to Copilot with **no corresponding open PR** (#584, #819,
  #868, #869) — indistinguishable from "in progress" without checking.
- Circular self-referential blockers: `#584` blocked by its own child `#819`;
  `#886`–`#889` each blocked by their own parent `#584`. A dependency that
  can never resolve freezes real work indefinitely with no error.
- A transient infra incident (#878, a stuck ARM operation) left open for 2.5
  months after the following PR proved it had cleared — an incident issue
  that outlives its incident becomes noise that hides real signal.

**4. AI-authored PRs that silently accrue zero verification.**
GitHub Copilot coding-agent PRs are opened as drafts and handed back without
being promoted. Separately, their CI workflows can land stuck at
`action_required` with **zero jobs run** — a state that looks identical to
"still queued" unless someone actively checks the Actions run list and
re-triggers it. Draft + stuck-CI is a silent no-signal state that can persist
indefinitely if treated as "no news is good news."

### The common thread

In every case above, the failure was not that something broke — it's that
**nothing measured whether it worked**, and the absence of a red signal was
mistaken for a green one. This is the specific thing to close off.

## Decision

State the governing principle plainly:

> **Agents propose. Humans and mechanical gates verify. Nothing merges, and
> nothing about the backlog is trusted, on the basis of it looking done —
> only on evidence that it is done.**

This applies identically to AI-agent-authored and human-authored work — the
gates don't get to know who wrote the diff.

### Concrete, mechanical countermeasures (not guidance — enforced gates)

1. **A required, blocking, offline pipeline gate proves the golden journey on
   every PR** (`make test-pipeline-local`, #1215/#1216/#1218): parse → trigger
   → orchestrate → acquire → enrich → artifact, against Azurite, no live
   Azure environment or network dependency. A broken pipeline fails CI before
   merge, not after a deploy attempt.
2. **Coverage is a required gate, not a report** (#1042): `diff-cover
   --fail-under 80` on changed Python lines, no `|| true` escape hatch.
   Test-first is mechanically enforced, not just a standing order.
3. **One canonical implementation per concept, checked by review and grep,
   not memory.** Duplicated core logic (haversine, centroid, and future
   cases found the same way) gets consolidated into a single module-owned
   function, tracked under the data-model stabilisation umbrella (#584), with
   a regression test asserting there's exactly one implementation where that
   makes sense.
4. **A PR is not done because it looks finished — it's done against the
   explicit Definition of Done** (linked issue, tests for new behaviour,
   green `make check`, marked ready not draft, Watchdog status reported —
   see `.github/copilot-instructions.md` "Delivery Workflow"). Draft status
   and stuck/`action_required` CI are treated as active blockers to resolve,
   never as an implicit pass — silence is not evidence.
5. **Backlog metadata is verified before it's trusted.** Stale assignments
   with no open PR, circular or self-referential blockers, and incident
   issues that have outlived their incident are corrected as part of any
   backlog review, not left as-is because closing/reassigning feels risky.
   Discovering one is treated as a signal to check for siblings of the same
   class, not a one-off.
6. **Every review comment gets a disposition, not a dismissal.** A Copilot
   or human review finding is either fixed (with a reply pointing at the
   fixing commit) or explicitly argued down and left unresolved with a
   reason — never silently left unresolved with no response.

## Consequences

- Verification work (writing the gate, fixing the duplication, correcting
  the backlog) is itself first-class delivery work, not overhead bolted onto
  "real" features — it's the reason the app can be redeployed and iterated
  on without repeating the flaky/broken era.
- This raises the bar for what "an agent finished the task" means: green CI
  alone is necessary but not sufficient if the CI gate itself is unproven
  (see §1 above) — a gate's own effectiveness must be checked (does it
  actually fail on the bad case?), not just its pass/fail output trusted.
- Re-enabling live deployment (the `DEPLOY_PAUSED` freeze, #1013) is gated on
  Stage 1's prove-it-works checks landing and being verified to actually
  fail on a broken golden journey — not merely on their being merged.
- This ADR is expected to gain amendments the same way ADR 0005 has, as new
  instances of the same failure classes are found — the point is the
  pattern-recognition habit, not a one-time cleanup.

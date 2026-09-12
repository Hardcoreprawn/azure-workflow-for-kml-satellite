# Local Reliability Audit

Date: 2026-09-11. Scope: the local integrated pipeline and its capacity oracle.
Primary persona: EUDR operator/compliance advisor who needs every accepted parcel
to produce traceable evidence or an explicit failure. Synthetic pipeline output
is not scientific validation or legal compliance certification.

## Follow-up: Tightened Checks (2026-09-12)

### Acceptance Follow-through

The parent now validates each winner against the reference of the task that was
actually dispatched, before accepting its result. Generator regressions reject
swapped, missing, and unexpected references while allowing out-of-order winners
with duplicate display names. The final expected-reference-set check remains.

Serverless summary completion additionally requires distinct, nonempty raw and
clipped paths, exactly one post-process source per raw download, and disjoint raw
and clipped output sets. Duplicate downloads, substituted sources, missing outputs,
and raw-as-clipped aliases produce `partial_imagery`; available metadata remains
visible. A valid no-imagery search also produces `partial_imagery`, not a claim of
complete imagery evidence.

The synthetic oracle compares raster shape, band types, nodata, valid-value count,
and extrema against the canonical constant-valued stub. Manifests must pass the
existing Pydantic schema. Known raster-reference fields, including frame-plan
references, must resolve to verified TIFFs; extensionless and JSON-as-raster
references are rejected.

Fresh 50-parcel control `c396a4af-4e90-4445-9088-93b01fce5ae7` produced 751
verified blobs. The final oracle reaccepted that healthy control, then rejected
eight real Azurite injections: corrupt, empty, truncated, wrong pixels, wrong
parcel geometry, stale metadata run identity, dangling manifest reference, and
missing blob. Each injection used a unique copied path; only probe-owned blobs
were removed. Reproduce against a control report using:

```sh
uv run python -m scripts.artifact_fault_probe \
  --control .capacity-evidence/requirements-control/report.json \
  --output .capacity-evidence/artifact-probes.json
```

Local evidence: `requirements-control/report.json` and
`requirements-artifact-probes-final.json` under `.capacity-evidence/`. The final
representative serial and parallel results are preserved separately as
`requirements-final-serial.json` and `requirements-final-parallel.json`, with
matching host logs. Both used fresh network-isolated storage and the real host.

This closes the tested false-acceptance gaps, not every reliability requirement.
Batch remains counter-based. Scene basenames reconcile raw to clipped outputs,
but there is no independent expected acquisition ledger: synthetic scene IDs are
random, and enrichment frames in this profile have unavailable scene references.
The tests do not establish arbitrary metadata semantic validity, general recovery,
scientific accuracy, or clock-valid capacity comparisons. Those issue criteria
remain open; no additional issue is marked closed by this evidence.

Local changes for #1495/#1496/#1497 and error masking in #1489 now reject the
tested false-success conditions. Final status reconciles successful records with
counts; progressive fan-in checks the exact original claim-reference set and
required phase fields; original child exceptions remain chained. Recorded Durable
time replaces wall time for output namespaces on replay.

The local oracle reads bounded JSON/GeoTIFF content and checks finite usable
pixels, CRS/bounds, run/parcel associations, submitted KML names/indices/bounds,
seven scenes per parcel, and manifest run identity. It reconciles the returned
metadata/raw/clipped/manifest inventory for this synthetic profile.

Final runs used one Python worker, 50 parcels, 350 imagery results, isolated
Azurite and the actual Functions host. Faults targeted an unfinished download in
the selected run's activity log. These observations are not a reliability rate.

| Case | Result | Evidence directory under `.capacity-evidence/` |
| --- | --- | --- |
| Fresh control | Passed: 751 verified blobs and exact inventory | `reliability-final-control` |
| Worker SIGKILL | Rejected: PID 51 exited 137, replacement PID 128 appeared, AOI child failure propagated; parent `Failed` at about 38s | `reliability-final-worker-kill` |
| Host stop/restart, storage retained | Passed: 751 verified blobs and exact inventory; completion observed about 306s after submission | `reliability-final-host-restart` |
| Exact duplicate Event Grid ID after completion | Rejected: trigger accepted delivery and Durable created a second execution generation | `reliability-final-duplicate-event` |

An earlier worker-kill run recovered with weaker fault correlation; it does not
cancel the final failure. The final worker report's case-level `status: Succeeded`
label was a harness defect: `runtimeStatus: Failed` and `accepted: false` are
authoritative. New reports derive that label from runtime status. Historical
evidence is preserved unchanged.

The duplicate run was stopped after proving a second generation; eventual artifact
and billing effects were not measured. Worker failure did not produce a complete
accepted evidence set; partial blob loss/cleanup was not quantified. Host restart
was process termination/relaunch, not machine or storage loss. Approximate poll
times are not performance benchmarks because host clock instability persists.
Polling transport errors during restart remain visible in the reports.

Follow-up review found no remaining blocking regression in these guard changes.
Batch completion still trusts Batch success counters without independent artifact
records. Synthetic imagery does not prove real-provider scene identity, scientific
accuracy, enrichment correctness, EUDR compliance, production auth, or billing.
Storage/provider interruption and exactly-once charging remain untested.

Next work at that point: publish the success checks with issue-level traceability,
then address worker-loss handling and completed-instance duplicate delivery as
separate slices. The #1498 results below select explicit terminal failure rather
than claiming automatic recovery.
The owner authorized publication on PR #1462. No deployments, production
configuration, security-waiver renewals, or host-clock edits were made.

## Worker-Loss Handling (#1498, 2026-09-12)

Policy: preserve bounded activity retries, do not replay the entire AOI, and
persist actionable parent failure status with parent/known-child correlation,
validated completion counts and `inspect_failure_then_resubmit`. Exceptions
remain chained; no raw exception text is added to custom status. This is failure
handling, not a claim that interrupted work always recovers.

Fresh isolated runs used the actual Functions host, one Python worker, synthetic
50-parcel input and disposable Azurite with no outbound network. The strict
control verified 350 imagery results and exactly 751 evidence artifacts.

| Run | Observation |
| --- | --- |
| Control `7035f934-36a0-455a-a9d2-c8a33738f5d4` | Completed; 751 content/identity-verified artifacts with exact inventory; completion observed about 44s after submission |
| SIGKILL `0fcd894f-65d8-4e9d-92db-37ca92134d55` | PID 49 killed during unfinished child `:aoi-1` download task 8; replacement PID 120; parent Failed observed about 39s after submission; accepted as `verified_terminal_failure`, never recovery |
| Reviewed SIGKILL `ab503b45-549d-44ee-9688-1415cf3dfdf3` | PID 49 killed during child `:aoi-0` download task 10; replacement PID 122; parent Failed about 39s after submission; unique failed-child/invocation correlation passed the final gate |

The terminal custom status identified failed child `:aoi-2`, zero results already
validated by the parent out of 50, and the recovery action. Its history contains
`acquire_composite` scheduling/completion followed by terminal failure, with no
download scheduling or activity-retry timers in that child. The interrupted
download child `:aoi-1` separately created and fired retry timers. This establishes
that the parent failure followed a child-invocation failure, not exhaustion of
the download activity's retry attempts.

The host recorded the AOI invocation failing with exit 137. Durable persisted
`Non-Deterministic workflow detected` because the interrupted replay returned no
previously scheduled acquisition actions. No code changed during either run.
Both errors are retained as evidence; the public status exposes correlation and
operator action, not raw host internals. An earlier run
`12431a6b-c733-43c0-8bb5-6e0d636fdfc3` was initially rejected because the oracle
expected exit 137 directly in child history. That report remains unchanged; the
corrected oracle requires the matching failed child history plus a unique
AOI invocation exit-137 match for the replay-error case. The same child execution's
replay start and completion must match the host invocation within 100 ms; the
invocation must span the recorded injection and matching PID exit. Missing,
stale-generation, or ambiguous correlations fail closed. This is timestamp-based
local evidence matching, not a distributed tracing or causal certainty claim.

Review caught and fixed both an overly broad log-only match and an offset-window
ambiguity. The final reviewed run passed the stricter driver end to end, retaining
failed child `:aoi-35`, execution `ce942ee420374ff9a141cf3043d3e74b`, invocation
`79f3bb94-a4ce-4840-b253-e6c4bdc5369a`, and PID 49 in `failureCorrelation`.
Its partial inventory snapshot contained 737 blobs, not a verified evidence set.
Run `c806c866-7132-45c2-b716-4cff210aa9b1` reached actionable parent failure but
was correctly rejected because three nearby child failures made attribution
ambiguous. All outcomes are retained; accepted samples do not define a recovery
rate. The concurrency profile remained unchanged throughout (one Python worker,
160 activity and 160 orchestration concurrency limits).

At observation time, the final failed run had 709 project-scoped blobs: 50
metadata, 658 imagery, and one copied KML; no enrichment manifest. This is an
inventory snapshot, not verified complete content, final sibling disposition,
or a measure of lost production data. Siblings can continue after parent failure.
No cleanup, exactly-once processing, billing effect, scientific correctness or
production reliability is claimed. The 600-second gate limit is not an SLA;
approximate poll durations are not performance comparisons.

Local raw reports, full correlated history, inventories and host logs are retained
under `.git/issue1498/` in `control`, `worker-kill`, `worker-kill-final`,
`worker-kill-correlated`, and `worker-kill-reviewed`. The control and
host-restart modes still require full artifact reconciliation. Missing failure
status/cause, failed controls, timeouts and ambiguous worker replacement are not
accepted. The historical evidence archived during workspace cleanup is unchanged.

Eventual recovery is tracked separately in #1506: immutable stage inputs/results,
append-only durable facts, stable idempotency keys, reconciliation that fills
missing outputs, and counts derived from unique committed results. Replaying a
stage twice must neither skip work nor double-count it. #1498 does not establish
that contract, and terminal-failure acceptance must not close the recovery work.

## Historical Verdict (Before Fixes)

Repeated happy-path execution works, but complete-and-correct delivery is not yet
established. There is no defensible reliability percentage from these runs.
The current runtime status and artifact oracle can miss injected omissions,
identity errors, and corrupt content. No actual production data loss was observed.
Clock instability blocks precise latency comparisons, not these logical fault
checks; reliability work does not need to wait for performance tuning.

## Historical Executed Checks

The new `tests/test_reliability_characterization.py` runs 13 deterministic cases
against the real aggregation, summary, and artifact-verifier functions. Its
assertions record current behavior, including defects; a passing characterization
suite must not be presented as a passing reliability acceptance gate. Promote the
defect cases to positive safety regressions when their issues are implemented.

| Injected condition | Observed result | Interpretation |
| --- | --- | --- |
| Healthy summary | `completed` | Baseline control |
| Explicit acquisition/download/post-process failure count (3 cases) | `partial_imagery` | Explicit failure accounting is visible |
| Missing metadata record | `completed` | Runtime false-completion gap, #1495 |
| Missing post-process result | `completed` | Runtime false-completion gap, #1495 |
| Missing parcel child result | `completed` | Expected identity set not reconciled, #1496 |
| Empty child result | `completed` | Missing sections default to zero, #1496 |
| First parcel substituted for second | `completed`; only first parcel in per-AOI summaries | Totals do not prove identity, #1496 |
| Child result is an exception | Secondary `AttributeError` about `.get` | Original cause obscured, existing #1489 |
| Missing artifact | Rejected | Storage existence check works |
| Empty artifact | Rejected | Nonzero-size check works |
| Corrupt nonempty artifact | Accepted without reading content | Content integrity unproven, #1497 |

These summary injections occur at the fan-in/summary boundary. They do not prove
that Durable naturally drops a task, delivers a duplicate child, or permits an
incomplete pending task set to finish. They demonstrate missing checks if an
upstream producer supplies incomplete or incorrect results.

The existing capacity oracle rejects headline-count deficits, which catches the
missing-metadata/post-process examples in that specific fixed-count exercise.
That does not repair the runtime `completed` status or prove parcel identity.

## Historical Real Storage Probe

In the existing network-isolated disposable Azurite instance, the audit wrote
two new blobs under a unique `reliability-audit/<uuid>/` prefix: `clipped.tif` and
`manifest.json`, both containing deliberately invalid plain text. The actual
`verify_artifacts` function accepted both. Replacing the raster with an empty
blob caused rejection; deleting it caused missing-blob rejection.

Only these two probe blobs were removed in cleanup. Previous experiment data was
not modified. This establishes an oracle blind spot, not pipeline-produced
corruption. The verifier currently checks properties/size, not format, schema,
pixel values, CRS, geometry, provenance, checksums, or parcel/scene association.

## Original Open Questions

- Recovery after a Python worker dies during an activity or after a full host
  restart, with Durable storage preserved.
- Duplicate Event Grid delivery and activity redelivery around the boundary
  between writing an artifact and acknowledging task completion.
- Eventual completion or explicit terminal failure after storage/provider
  interruption; absence of permanently stranded accepted jobs.
- Exactly one logical artifact/usage charge per intended work item despite
  repeated physical execution. Retry declarations alone do not prove this.
- Correct attribution when parcels share display names, uploads run concurrently,
  or two users submit similar geometry. Local enterprise tickets do not prove
  production ownership, auth, quota, or billing behavior.
- Real imagery quality, parcel coverage, CRS correctness, nodata handling,
  temporal coverage, scientific calculations, or suitability for an EUDR decision.
  Synthetic mode deliberately bypasses external providers and some enrichment.

## Original Acceptance Plan

First make success trustworthy: reconcile expected parcel identities, enforce
required-output completeness, and validate artifact contents using existing
format/schema readers and explicit fixture expectations (#1495/#1496/#1497).
Preserve original failure causes (#1489). These are separately scoped issues,
not permission for one broad runtime rewrite.

Then run a disposable interruption/redelivery matrix: terminate one worker during
an observed activity, restart the host while preserving storage, redeliver the
same event, and interrupt storage temporarily. Trigger faults from observable
milestones rather than blind delays. Compare submitted work identities against
terminal outcomes and artifact/usage identities; require every item to be either
correctly completed or explicitly failed, with no missing or substituted parcel,
no false success, no orphaned accepted job, and no duplicate logical charge.
Do not assume exactly-once physical execution from Durable retries.

## Initial Audit Validation

Focused command:
`make test-fast TESTS="tests/test_reliability_characterization.py tests/test_pipeline.py tests/test_aoi_orchestrator_coverage.py tests/test_orchestrator_phases_extra_coverage.py tests/test_local_capacity.py"`

Result: 194 tests passed, including 13 new characterization cases. The real
Azurite probe independently confirmed corrupt/empty/missing artifact behavior.
Handoff gate: `make check`. No runtime fixes, production configuration changes,
commits, deployments, or host clock modifications are part of this audit.

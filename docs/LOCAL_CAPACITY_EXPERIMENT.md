# Local Capacity Experiment (#1492)

This is an in-progress local Python 3.12 experiment, not a production sizing
recommendation. Reuse the external `scale-50.json` or `scale-200.json` catalogue.
The runner requires initialized disposable Azurite and the existing Functions
image with a pre-cached extension bundle. It writes an enterprise test ticket;
never run it against shared or cloud storage.

Inside the network-isolated workload container, from the repository root:

```bash
uv run python -m scripts.local_capacity --workers 2 --parcels 50 \
  --output /workspace/.capacity-evidence/unique-run-name
```

On the Docker-controlling host, wrap that container command to capture resources:

```bash
uv run python -m scripts.capacity_resources \
  --output .capacity-evidence/unique-run-name-resources.jsonl \
  docker run <the workload container arguments>
```

The resource wrapper expects the workload container name
`canopex-local-exercise-runner` and storage container name
`canopex-local-exercise-azurite`. It samples only those containers, requires
evidence for both, and exits with the workload's status. Sampling errors fail
the wrapper. Output files cannot overwrite previous evidence. Create fresh
disposable storage for each measured run; leave unrelated Docker resources alone.

## Startup And Reliability

- Profiles select 1, 2, or 4 Python processes, eight activity threads per process,
  and 160 Durable activity/orchestrator slots. They disable development file
  watching, without changing normal development or production configuration.
- Health retry attempt numbers are not worker counts. After health succeeds,
  `STARTUP` reports requested workers, distinct observed PIDs, initialization
  evidence, elapsed time, and the failure deadline on state changes or every
  two seconds. Worker readiness allows 20 seconds plus ten seconds per additional
  requested worker: 20/30/50 seconds for the 1/2/4-worker profiles, after health
  succeeds. These are upper bounds, not mandatory delays. Local health and
  worker readiness checks run at 100 ms
  intervals and return immediately when ready; there is no mandatory warm-up
  sleep. This is bounded polling, not an event-driven notification mechanism.
- Initialization evidence includes reused initialized Python channels as well as
  newly initialized workers. Narrow worker debug logging exposes the reused
  channel path. A generic initialization message alone is not a worker count.
- The Functions host staggers extra worker launches by ten seconds by default.
  Host 4.1051.300 reads this interval from its bundled worker configuration;
  `languageWorkers__python__processCount__processStartupInterval` was tested and
  ignored, so the profile does not set it. The version-specific
  [configuration parser](https://github.com/Azure/azure-functions-host/blob/v4.1051.300/src/WebJobs.Script/Workers/Rpc/Configuration/WorkerConfigurationProviderBase.cs)
  explicitly overrides process count from the environment, not startup interval.
  The capacity profile does not patch the bundled runtime.
- By default, no parcels are submitted until full worker readiness succeeds.
  `--startup-under-load` instead submits immediately after host health succeeds,
  allowing ready workers to process while the host starts the rest. It records
  initial/final worker PIDs and reports observed worker membership changes.
  Both modes reject disappearing/replaced observed workers and require the full
  initialized pool by completion. The host is stopped when the runner exits.
- Results require exact parcel, acquisition, download, post-processing, metadata,
  and unique artifact counts, zero reported failures, and nonempty blobs for all
  reported artifacts and the manifest.
- SDK DNS/retry markers, failed activities, and unexpected tracebacks fail
  acceptance. The exact successful Fiona-to-lxml fallback is explicitly recorded
  as a warning (#1493), not silently presented as Fiona coverage.

## Verified Repairs (2026-09-10)

A rejected one-worker run took about 305 seconds after a source modification
triggered a host reload and cancelled an activity. The source mtime preceded
the shutdown by less than one second. A controlled timestamp-only touch reproduced
the reload. The same probe with profile file watching disabled retained one worker
PID and one initialization.

The original Docker streaming collector produced no samples. Its replacement
uses bounded `docker stats --no-stream` calls and flushes each JSON sample.
The one-worker repaired run completed 50 parcels in 40.78 seconds and verified
751 blobs, with samples from both containers. In the measured interval, sample
means were approximately 242% CPU for Functions and 96% for Azurite; Docker 100%
means one CPU core. These are sampled observations, not integrated CPU time.

The initial two-worker readiness check falsely waited for a second generic
initialization message. A probe confirmed two live worker PIDs, one reused-channel
initialization, and one new-worker initialization. The corrected check accepted
both immediately. A subsequent two-worker run completed in 57.90 seconds with
751 verified blobs. Do not compare these two runs as a controlled speedup result:
the runner/logging changed between them and each is a single observation.

A four-worker attempt hit the old 20-second readiness deadline as its fourth
process appeared. Another initialized just before the deadline (displayed as
20 seconds after rounding), then completed 50 parcels in 56.49 seconds with
751 verified blobs. This exposed insufficient startup margin, not a reason to
accept partially initialized pools. The readiness allowance now scales by worker
count while checks still return immediately on success. Workload elapsed time
starts after worker readiness and excludes startup.

## Startup Under Load

Add `--startup-under-load` to the runner command to exercise work arriving before
the configured pool is fully started. This removes the benchmark's all-workers
barrier, not the Functions host's launch spacing. The host still starts a fixed
configured pool; this is not demand-based autoscaling. The local Event Grid
webhook acknowledgement also does not measure the authenticated submission API.

Verified offline run `startup-load-w4-50` submitted with two workers present and
completed 50 parcels in 55.57 seconds, validating 751 nonempty artifact blobs.
The host log records parsing at 22:56:35.959 UTC, third-worker initialization at
22:56:44.909, and fourth-worker initialization at 22:56:55.244 on 2026-09-10.
Thus processing began about 19 seconds before the last worker initialized.
This is synthetic pipeline execution, not real provider throughput evidence.

Reports mark `startupUnderLoad` and include `finalWorkerPids`. In this mode,
`elapsedSeconds` includes worker ramp-up after submission but excludes the
initial host-health wait. Do not mix these results into warm-capacity averages.

## Observability Evidence

Install the `dev` extra (`uv sync --extra dev`) for the read-only Azure queue
collector. Container images used for observation also need `azure-storage-queue`;
the image used for the earlier experiments predates this dependency. For an
offline run, install the pinned package from the lockfile into a local dependency
directory and mount it on the container's `PYTHONPATH`, or prepare the dev image
before disconnecting its network. Do not install packages from the network during
a measured run.

Each run now writes:

- `timeline.json`: whitelisted Durable history metadata, task identity, schedule,
  activity start/finish and Durable completion timestamps, per-activity nearest-rank
  p50/p95/max timings with sample counts, longest queue delays, timer events,
  first per-AOI sub-orchestrator completion, and an aligned load timeline.
- `queues.json`: approximate counts for activity/control queues, up to 32 visible
  peeked messages per queue, oldest peeked insertion age, sample timestamps,
  collection duration and explicit collection errors. Peeking does not receive,
  hide, delete or renew messages; payloads are neither inspected nor saved.
- `samples.json`: process CPU/RSS/thread samples, now with UTC timestamps alongside
  monotonic time for alignment with queue, task and Docker resource samples.
- `report.json`: telemetry coverage counts, first-AOI timing, queue sample count,
  and separate host-start/health-ready milestones. Collector failures or incomplete
  task timing invalidate acceptance and retain available evidence. Shutdown errors
  are also recorded without replacing an original run error or skipping reports.

Timing joins use instance ID and task ID, with execution generation checked against
history. Missing or ambiguous events remain explicitly unmeasured. Concurrent
console output can concatenate timestamped records onto one line; the parser
recognizes event boundaries rather than assuming one event per line.

`scheduleToStartSeconds` includes Durable scheduling/dispatch delay, not just time
in the physical queue. `executionWallSeconds` includes worker execution and its
internal I/O waits; it is not CPU time. `completionEventLagSeconds` ends at the
completion event's creation timestamp recorded in history, not at its consumption
or the next orchestrator resume. It does not measure control-queue handoff latency.
No payload, geometry, URL or user data is copied into history evidence.

Load counts use matched task events and explicitly count unknown start/finish
evidence. They are pool-wide, not task-to-worker attribution. Queue counts are
approximate and may include invisible messages; the oldest peeked message is not
a guarantee of the oldest runnable task. Sampling is every two seconds plus the
time spent collecting; collection duration is recorded. The first AOI metric
means its sub-orchestrator completed, not that EUDR evidence or enrichment is ready.

The first instrumented offline 50-parcel run completed in 55.24 seconds, verified
751 blobs, captured 1,256 scheduled tasks and 25 queue samples, and completed its
first AOI at 24.37 seconds. Reprocessing its retained evidence after fixing
concatenated-log parsing matched all 1,256 starts and finishes without ambiguity.
The original report remains preserved as collected. This is one synthetic run,
not evidence for a production concurrency setting or collector overhead estimate.

The final reviewed run `telemetry-final-w4-50` completed in 55.50 seconds with
751 validated blobs and complete timings for all 1,256 tasks: zero missing,
ambiguous or invalid timing records. It captured 25 queue samples and first AOI
completion at 27.06 seconds. Median schedule-to-start / activity wall time was
4.82 / 0.077 seconds for downloads and 5.32 / 0.111 seconds for post-processing.
The activity queue peaked at approximately 245 messages; the sampled load timeline
peaked at 242 scheduled-not-started tasks and 13 active tasks. Sampled peaks are
not exact concurrency maxima. No durable timer events occurred in this synthetic
run. These observations motivate dispatch/concurrency experiments, not a conclusion
about the specific resource or limit responsible for the delay.

Remaining measurements include per-worker task ownership, activity-internal I/O
versus compute, exact ready/in-flight queue accounting, and repeated fixed-code
arrival-rate/concurrency comparisons. Do not infer these from the new counters.

## Repeated Warm Comparison (2026-09-10)

Completed three fresh-storage 50-parcel repetitions per worker count, with eight
threads per worker and 160 Durable activity/orchestrator slots. Profile order was
1/2/4, then 2/4/1, then 4/1/2. The final two-worker attempt was interrupted by a
shared-terminal command and repeated separately as `compare-r5-w2`; the interrupted
`compare-r4-w2` is excluded and retained. `compare-r1-w1` was rejected before upload:
one worker emitted both reused-channel and dispatcher initialization messages.
The readiness counter now recognizes that single-worker case while still requiring
the exact requested number of distinct worker PIDs; its regression test passes.

Accepted evidence is `compare-r{2,3,4}-w1`, `compare-r{2,3,5}-w2`, and
`compare-r{2,3,4}-w4` under `.capacity-evidence/`. Every accepted run verified 751
nonempty blobs and complete start/finish timing joins for all 1,256 tasks. Runner
and fixture hashes match across all nine reports; all four harness source hashes
were unchanged across the measured series. These are warm-pool, synthetic runs.

| Workers | Runner elapsed seconds (three runs) | Median | First AOI median (UTC seconds) | Root completion median (UTC seconds) | Completion observation lag median (UTC seconds) |
| --- | --- | --- | --- | --- | --- |
| 1 | 39.18, 42.84, 56.31 | 42.84 | 35.39 | 44.55 | 0.87 |
| 2 | 56.19, 55.92, 55.25 | 55.92 | 27.10 | 43.39 | 18.04 |
| 4 | 58.77, 56.08, 56.03 | 56.08 | 24.02 | 40.03 | 23.49 |

Runner elapsed uses monotonic time. UTC metrics start at `startedUtc`; root
completion uses the root Durable `ExecutionCompleted` history timestamp, and
observation lag ends at `finishedUtc`. They are not interchangeable timebases:
process samples show UTC advancing 2.58-5.27 seconds more than monotonic time per
run, including individual jumps around 2.6 seconds. Positive durations and complete
joins do not detect this problem. The reports remain unchanged as collected, but
their `accepted` flag is correctness/collection acceptance, not timing validity.

Multi-worker polling also entered `Unknown` before observing completion. The
diagnostics endpoint has a rate-limit guard, and the runner currently treats JSON
without `runtimeStatus` as `Unknown` without recording HTTP status. Rate limiting
is therefore a hypothesis, not a confirmed explanation of these runs. Do not
interpret the 14-24 second recorded multi-worker observation tails as computation.

For context, medians of per-run sampled Functions-container CPU means were
246%, 278%, and 285% for 1/2/4 workers; Azurite was 104%, 113%, and 109%.
These include the host and collector, use Docker's multi-core percentage convention,
and select samples between UTC submission and root completion. They are not CPU
integrals or per-worker attribution; clock discontinuities also limit alignment.
Azurite CPU use alone does not establish a storage bottleneck.

No production worker-count recommendation follows from this batch. Earlier first
AOI completion with more workers is a useful signal, but precise dispatch latency,
throughput gains, and the slower one-worker repetition require cleaner measurement.
The next diagnostic below adds polling and clock validation. Keep rate-limit gates
unchanged; repeat the 50-parcel comparison on a stable clock before confirming
at 200 parcels.

## Measurement-Quality Diagnostic (2026-09-10)

The capacity runner now uses the existing harness polling interval of three
seconds. The diagnostics endpoint allows 30 requests per 60 seconds; the prior
one-second experiment interval could exceed that budget. No endpoint, limiter,
auth, or production concurrency settings changed.

`polls.json` retains response UTC/monotonic time, request duration, HTTP status,
allowlisted runtime status, and response category. HTTP errors, transport errors,
malformed JSON, and malformed status payloads no longer appear as `Unknown`.
Response bodies are not copied into these observations. This is not a redaction
guarantee for the entire existing harness report or host log: they retain output
evidence and pre-existing failure diagnostics.

`report.json` includes `measurementQuality`, with clock sample count, maximum
UTC-minus-monotonic offset range, tolerance, polling error count, and validity.
Acceptance requires at least two strictly increasing monotonic samples, an offset
range no greater than 0.1 seconds, and nonempty polling evidence without errors.
Initial HTTP 404 observations are allowed while the instance becomes visible.
The 0.1-second tolerance is a local measurement-quality bound, not a performance
target or an allowance for the multi-second jumps observed here. The offset range
also catches jumps that later cancel. Raw evidence and the rejection reason are
saved when validation fails; complete task joins alone no longer pass acceptance.

Fresh-storage four-worker run `compare-r6-w4` completed the 50-parcel workload in
47.4988 monotonic seconds, verified all 751 blobs, and joined all 1,256 task
timings. All 16 polling responses were HTTP 200, with no polling errors. Its
recorded UTC completion-observation lag was 2.3031 seconds. This is a diagnostic
observation, not a demonstrated speedup over the previous batch.

The run was correctly rejected: 48 process samples showed an offset range of
5.072263 seconds. `accepted` and `measurementQuality.valid` are false, while
artifact and task-completeness checks passed. Further worker repetitions were
stopped because precise UTC latency comparisons remain invalid.

A separate 35-sample idle probe compared realtime, monotonic, and Linux
`CLOCK_BOOTTIME`. Realtime advanced by 2.543521 seconds relative to both other
clocks between samples 25 and 30; boottime and monotonic stayed aligned within
microseconds. This reproduces realtime clock adjustment without the workload and
does not have the signature of ordinary suspend time accounted for by boottime.
The source of the adjustment is not established. No host clock, time service,
container privilege, or system setting was changed.

Next prerequisite: investigate the host/VM time source or move the comparison to
a clock-stable runner. Do not disable the quality gate, inflate its tolerance, or
silently correct historical task timestamps to obtain a passing benchmark.

## Remaining Acceptance Work

Repeat the comparison after resolving the realtime-clock adjustment;
retain runner/fixture hashes and all rejected runs. Confirm at 200 parcels
only after the smaller comparison is healthy. No sustained capacity, complete
per-parcel scientific enrichment, EUDR compliance, or production tier/auth/tenant
acceptance is established by these synthetic runs.

Validation: `make test-fast TESTS="tests/test_local_capacity.py"`, then `make check`.

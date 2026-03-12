# Stress Test Validation (Issue #14)

## Scope

This validation covers concurrent upload behavior for at least 20 KML inputs, aligned with PID NFR-2, FR-5.4, and AC-10.

## Test Entry Point

- Test file: tests/integration/test_stress_pipeline.py
- Workflow: .github/workflows/stress-e2e.yml
- Marker profile: e2e + slow

## What Is Verified

1. 20 concurrent uploads are submitted to the live pipeline.
2. Every upload resolves to an independent orchestration instance.
3. Every orchestration reaches runtimeStatus=Completed.
4. Metadata artifact paths are unique across all concurrent runs.
5. Metadata blobs exist and are non-empty in the output container.
6. Throughput and latency distribution are measured and emitted as test properties.

## Runtime Metrics Captured

- concurrent_uploads
- total_duration_s
- throughput_per_s
- duration_mean_s
- duration_p50_s
- duration_p95_s
- duration_max_s

## Operational Review Checklist

Use the stress workflow run window to inspect live telemetry:

1. Function App instance count scale-out behavior
2. Memory pressure and host throttling events
3. Activity retry spikes and provider-side latency shifts
4. Event Grid and Durable orchestration backlog growth

## Production Recommendations

1. Keep blob naming fully unique per upload trigger to preserve idempotency under contention.
2. Alert on sustained orchestration queue growth and long-tail latency (P95/P99).
3. Preserve host-key retrieval fail-fast behavior in CI workflows.
4. Re-run stress validation after infrastructure/runtime changes and before major releases.

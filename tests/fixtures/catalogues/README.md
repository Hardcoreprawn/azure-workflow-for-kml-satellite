# Fixture Catalogues

The local E2E runner consumes a versioned JSON catalogue, not a case list in
Python. `representative.json` is the small smoke catalogue. Fixture files stay
outside the runner; another directory or checked-out fixture repository can
provide its own catalogue.

```bash
uv run python scripts/e2e_local.py --scenario representative \
  --manifest /path/to/fixture-library/catalogue.json --dry-run-matrix
uv run python scripts/e2e_local.py --scenario representative \
  --manifest /path/to/fixture-library/catalogue.json \
  --execution parallel --concurrency 3
```

Execution requires initialized disposable Azurite storage and Functions Core
Tools. The runner owns the Functions host, not storage startup or cleanup.

## Format

```json
{
  "schemaVersion": 1,
  "cases": [
    {
      "caseId": "geometry-001",
      "inputPath": "../single_polygon.kml",
      "container": "kml-input",
      "expectedStatus": "Succeeded"
    }
  ]
}
```

- Paths resolve relative to the catalogue, not the shell working directory.
- Entries run in catalogue order in serial mode. Parallel results are saved in
  catalogue order even when completion order differs.
- IDs must be unique and stable. KML and KMZ may have the same stem but need
  different case IDs. Files must exist before the host starts.
- Unknown fields, duplicate IDs, empty catalogues, and unsupported versions or
  expected outcomes are rejected before execution.
- Use trigger-compatible input containers such as `kml-input`. Initialize shared
  containers before parallel execution. Different files with the same basename
  cannot share an input container: the loader rejects these collisions because
  the current uploader uses that basename as the blob key. Repeats of the same
  resolved file remain valid.
- `Succeeded` currently means terminal `Completed`, at least one completed
  download, and nonempty raw imagery paths. It does not assert every AOI succeeded,
  numerical accuracy, or user isolation.
- This initial schema supports positive cases only. Negative cases require
  explicit stage/error assertions in #1455; an arbitrary failure or timeout must
  never count as a successful rejection test.

## Local Scale Exercises

`scale-50.json` and `scale-200.json` opt into the existing 50- and 200-polygon
fixtures. They are not part of the fast smoke default. These workloads need an
explicit local enterprise ticket: without one the free-tier AOI limit rejects
them. Against disposable Azurite, in the same container/network namespace used
by the harness:

```bash
PYTHONPATH=scripts:. uv run python -c \
  'from corpus_runner import _upload_ticket; _upload_ticket("medium_50.kml", "kml-input", user_id="offline-capacity-exercise")'
uv run python scripts/e2e_local.py --scenario representative \
  --manifest tests/fixtures/catalogues/scale-50.json \
  --orchestration-timeout-seconds 600
```

For 200 AOIs, replace `medium_50.kml` with `monster_200.kml` in the ticket command
and select `scale-200.json`. This direct trigger/ticket path tests internal
workload handling, not authenticated submission, production tier admission,
tenant isolation, or EUDR compliance. Do not use it against shared/cloud storage.

On 2026-09-10, isolated Docker runs with a pre-cached Functions extension bundle
and no external network access produced:

| Workload | Elapsed (excluding host startup) | AOIs | Downloads / raw paths |
| --- | ---: | ---: | ---: |
| Three smoke cases, serial | 9.64 s | 2 per case | 14 / 14 per case |
| Three smoke cases, parallel (3) | 6.84 s | 2 per case | 14 / 14 per case |
| One 50-AOI case | 42.67 s | 50 | 350 / 350 |
| One 200-AOI case | 236.08 s | 200 | 1400 / 1400 |

The serial and parallel comparison used fresh storage for each run. Scale runs
used the same local Azurite after the parallel run; these are single observations,
not controlled throughput benchmarks. Counts were checked separately from the
runner's success-only oracle, and host logs had no SDK DNS/retry markers.
The synthetic provider emits small rasters; remote mosaic/NDVI and weather
evidence are intentionally unavailable. These results do not measure full-size
imagery, sustained capacity, CPU/memory ceilings, or scientific accuracy.

## Growth Plan

Keep the three smoke entries as a fast subset. Grow the fixture library through
issues #1454 (mixed inputs and user distribution), #1455 (large AOIs and explicit negative
contracts), and #1456 (evaluation reports). Reuse existing fixtures and corpus
baselines rather than duplicating geometry in Python. Wave selection, coverage
metadata, expected AOI counts, and scientific baseline comparisons belong in those
follow-up slices. A filename or successful upload alone is not an acceptance oracle.

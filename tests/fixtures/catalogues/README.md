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

## Growth Plan

Keep the three smoke entries as a fast subset. Grow the fixture library through
issues #1454 (mixed inputs and user distribution), #1455 (large AOIs and explicit negative
contracts), and #1456 (evaluation reports). Reuse existing fixtures and corpus
baselines rather than duplicating geometry in Python. Wave selection, coverage
metadata, expected AOI counts, and scientific baseline comparisons belong in those
follow-up slices. A filename or successful upload alone is not an acceptance oracle.

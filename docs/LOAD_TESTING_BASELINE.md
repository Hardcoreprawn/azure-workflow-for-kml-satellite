# Load Testing Baseline

Issue: #320

## Purpose

Establish an empirical MVP baseline before major scaling architecture work.

The baseline runner executes four scenarios against the local pipeline:

1. `baseline` - 1 AOI
2. `moderate_bulk` - 50 AOIs
3. `stress_bulk` - 200 AOIs
4. `massive_polygon` - 1 very large polygon

## Prerequisites

1. Start Azurite and initialize storage:

```bash
make dev-storage
```

1. Start local Functions host:

```bash
make dev-func
```

## Run

```bash
uv run python scripts/load_baseline.py --runs-per-scenario 3 --concurrency 2
```

Options:

- `--timeout`: per-run timeout seconds (default `600`)
- `--poll-interval`: orchestrator polling interval in seconds (default `3.0`)
- `--container`: target blob container (default `kml-input`)
- `--out-dir`: report output directory (default `docs/baselines`)

## Outputs

For each run, the script writes:

- `docs/baselines/load-baseline-<timestamp>.json`
- `docs/baselines/load-baseline-<timestamp>.md`

The report includes:

- success rate by scenario
- p50/p95 duration by scenario
- timeout/failure counts
- throttling, timeout, and memory signal heuristics
- orchestration instance IDs for follow-up diagnostics

## Interpretation

Treat the first scenario with degraded success rate, elevated timeouts, or throttle
signals as the current MVP threshold boundary.

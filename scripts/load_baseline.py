"""Load-testing baseline runner for issue #320.

This script exercises the local pipeline with four scenarios and writes a baseline
report that captures success/failure thresholds:

1. baseline        - 1 AOI
2. moderate_bulk   - 50 AOIs
3. stress_bulk     - 200 AOIs
4. massive_polygon - 1 very large polygon

It uploads KML files to Azurite, triggers Event Grid notifications, polls
`/api/orchestrator/{instance_id}`, and records terminal status + duration.

Usage:
  uv run python scripts/load_baseline.py
  uv run python scripts/load_baseline.py --runs-per-scenario 3 --concurrency 2
  uv run python scripts/load_baseline.py --timeout 900 --out-dir docs/baselines
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from generate_monster_kml import generate_kml
from simulate_upload import (
    DEFAULT_EVENT_GRID_FUNCTION_NAME,
    FUNC_BASE,
    check_func_host,
    fire_event_grid,
    upload_kml,
)

TERMINAL_STATUSES = {"Completed", "Failed", "Canceled", "Terminated"}


@dataclass
class RunResult:
    scenario: str
    run_id: int
    aoi_count: int
    instance_id: str
    runtime_status: str
    duration_s: float
    timed_out: bool
    had_throttle_signal: bool
    had_timeout_signal: bool
    had_memory_signal: bool
    raw_status: dict[str, Any]


@dataclass
class ScenarioSummary:
    scenario: str
    aoi_count: int
    runs: int
    success_count: int
    failure_count: int
    timeout_count: int
    throttle_signal_count: int
    timeout_signal_count: int
    memory_signal_count: int
    success_rate: float
    duration_p50_s: float
    duration_p95_s: float


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _generate_massive_polygon_kml(path: Path) -> None:
    """Generate one very large polygon near the equator for stress testing."""
    coords = [
        "-70.0,-5.0,0",
        "-70.0,3.0,0",
        "-62.0,3.0,0",
        "-62.0,-5.0,0",
        "-70.0,-5.0,0",
    ]
    kml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document>\n"
        "    <name>massive_polygon</name>\n"
        "    <Placemark>\n"
        "      <name>MassiveAOI</name>\n"
        "      <Polygon>\n"
        "        <outerBoundaryIs><LinearRing><coordinates>"
        + " ".join(coords)
        + "</coordinates></LinearRing></outerBoundaryIs>\n"
        "      </Polygon>\n"
        "    </Placemark>\n"
        "  </Document>\n"
        "</kml>\n"
    )
    path.write_text(kml, encoding="utf-8")


def _poll_status(
    instance_id: str,
    timeout_s: int,
    poll_interval_s: float,
) -> tuple[str, dict[str, Any], bool]:
    url = f"{FUNC_BASE}/api/orchestrator/{instance_id}"
    start = time.monotonic()
    last_payload: dict[str, Any] = {}

    while time.monotonic() - start < timeout_s:
        try:
            resp = httpx.get(url, timeout=10.0)
        except httpx.HTTPError:
            time.sleep(poll_interval_s)
            continue

        if resp.status_code == 404:
            time.sleep(poll_interval_s)
            continue

        payload = resp.json()
        last_payload = payload if isinstance(payload, dict) else {}
        status = str(last_payload.get("runtimeStatus") or "Unknown")
        if status in TERMINAL_STATUSES:
            return status, last_payload, False

        time.sleep(poll_interval_s)

    return "TimedOut", last_payload, True


def _contains_signal(payload: dict[str, Any], *keywords: str) -> bool:
    text = json.dumps(payload, default=str).lower()
    return any(k.lower() in text for k in keywords)


def _run_one(
    scenario: str,
    source_kml: Path,
    aoi_count: int,
    run_id: int,
    timeout_s: int,
    poll_interval_s: float,
    container: str,
    function_name: str,
    function_key: str | None,
) -> RunResult:
    run_file = source_kml.parent / f"{source_kml.stem}-run{run_id}.kml"
    shutil.copy2(source_kml, run_file)

    start = time.monotonic()
    blob_name, blob_url, content_length = upload_kml(run_file, container)
    try:
        instance_id = fire_event_grid(
            blob_url,
            blob_name,
            content_length,
            container,
            function_name=function_name,
            function_key=function_key,
            strict=True,
        )
        status, payload, timed_out = _poll_status(instance_id, timeout_s, poll_interval_s)
    except RuntimeError as exc:
        duration_s = time.monotonic() - start
        return RunResult(
            scenario=scenario,
            run_id=run_id,
            aoi_count=aoi_count,
            instance_id="",
            runtime_status="TriggerRejected",
            duration_s=duration_s,
            timed_out=False,
            had_throttle_signal=False,
            had_timeout_signal=False,
            had_memory_signal=False,
            raw_status={"error": str(exc)},
        )

    duration_s = time.monotonic() - start

    had_throttle_signal = _contains_signal(payload, "429", "throttle", "too many requests")
    had_timeout_signal = _contains_signal(payload, "timeout", "timed out")
    had_memory_signal = _contains_signal(payload, "out of memory", "memory", "oom")

    return RunResult(
        scenario=scenario,
        run_id=run_id,
        aoi_count=aoi_count,
        instance_id=instance_id,
        runtime_status=status,
        duration_s=duration_s,
        timed_out=timed_out,
        had_throttle_signal=had_throttle_signal,
        had_timeout_signal=had_timeout_signal,
        had_memory_signal=had_memory_signal,
        raw_status=payload,
    )


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def _summarize(scenario: str, aoi_count: int, runs: list[RunResult]) -> ScenarioSummary:
    durations = [r.duration_s for r in runs]
    success_count = sum(1 for r in runs if r.runtime_status == "Completed")
    failure_count = sum(
        1
        for r in runs
        if r.runtime_status in {"Failed", "Canceled", "Terminated", "TriggerRejected"}
    )
    timeout_count = sum(1 for r in runs if r.timed_out)

    return ScenarioSummary(
        scenario=scenario,
        aoi_count=aoi_count,
        runs=len(runs),
        success_count=success_count,
        failure_count=failure_count,
        timeout_count=timeout_count,
        throttle_signal_count=sum(1 for r in runs if r.had_throttle_signal),
        timeout_signal_count=sum(1 for r in runs if r.had_timeout_signal),
        memory_signal_count=sum(1 for r in runs if r.had_memory_signal),
        success_rate=(success_count / len(runs)) if runs else 0.0,
        duration_p50_s=statistics.median(durations) if durations else 0.0,
        duration_p95_s=_p95(durations),
    )


def _write_markdown(
    output_path: Path,
    summaries: list[ScenarioSummary],
    run_results: list[RunResult],
    generated_at: str,
) -> None:
    threshold = "No clear failure threshold detected in this run"
    for s in summaries:
        if s.success_rate < 1.0 or s.timeout_count > 0 or s.throttle_signal_count > 0:
            threshold = (
                f"Potential threshold at {s.scenario} ({s.aoi_count} AOIs): "
                f"success_rate={s.success_rate:.0%}, timeouts={s.timeout_count}, "
                f"throttle_signals={s.throttle_signal_count}"
            )
            break

    lines = [
        "# Load Testing Baseline",
        "",
        f"Generated: {generated_at}",
        "",
        "## Scenario Summary",
        "",
        "| Scenario | AOIs | Runs | Success | Failures | Timeouts | P50 (s) | P95 (s) | "
        "Throttle Signals |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for s in summaries:
        lines.append(
            f"| {s.scenario} | {s.aoi_count} | {s.runs} | {s.success_rate:.0%} | "
            f"{s.failure_count} | {s.timeout_count} | {s.duration_p50_s:.2f} | "
            f"{s.duration_p95_s:.2f} | {s.throttle_signal_count} |"
        )

    lines.extend(
        [
            "",
            "## Threshold Signal",
            "",
            f"- {threshold}",
            "",
            "## Run Details",
            "",
            "| Scenario | Run | Instance ID | Status | Duration (s) | Timed Out | 429/Throttle | "
            "Timeout Signal | Memory Signal |",
            "| --- | ---: | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )

    for r in run_results:
        lines.append(
            f"| {r.scenario} | {r.run_id} | {r.instance_id} | {r.runtime_status} | "
            f"{r.duration_s:.2f} | {r.timed_out} | {r.had_throttle_signal} | "
            f"{r.had_timeout_signal} | {r.had_memory_signal} |"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local load-testing baseline scenarios")
    parser.add_argument(
        "--runs-per-scenario",
        type=int,
        default=1,
        help="How many runs per scenario",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Concurrent orchestration starts",
    )
    parser.add_argument("--timeout", type=int, default=600, help="Timeout per run (seconds)")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Orchestrator poll interval",
    )
    parser.add_argument("--container", default="kml-input", help="Target blob container")
    parser.add_argument(
        "--event-grid-function-name",
        default=DEFAULT_EVENT_GRID_FUNCTION_NAME,
        help="Function name for Event Grid webhook (default: blob_trigger)",
    )
    parser.add_argument(
        "--event-grid-function-key",
        default=os.getenv("EVENT_GRID_FUNCTION_KEY"),
        help="Event Grid system key (or set EVENT_GRID_FUNCTION_KEY env var)",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/baselines",
        help="Directory for JSON/Markdown baseline artifacts",
    )
    args = parser.parse_args()

    if args.runs_per_scenario < 1:
        raise SystemExit("--runs-per-scenario must be >= 1")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")

    if not check_func_host():
        raise SystemExit("Function host not reachable at localhost:7071. Start with: make dev-func")

    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(UTC).isoformat()
    stamp = _now_stamp()

    all_run_results: list[RunResult] = []
    summaries: list[ScenarioSummary] = []

    with tempfile.TemporaryDirectory(prefix="treesight-load-baseline-") as tmp:
        tmp_dir = Path(tmp)
        baseline_kml = tmp_dir / "baseline_1_aoi.kml"
        moderate_kml = tmp_dir / "moderate_50_aoi.kml"
        stress_kml = tmp_dir / "stress_200_aoi.kml"
        massive_kml = tmp_dir / "massive_polygon.kml"

        generate_kml(1, str(baseline_kml))
        generate_kml(50, str(moderate_kml))
        generate_kml(200, str(stress_kml))
        _generate_massive_polygon_kml(massive_kml)

        scenarios: list[tuple[str, int, Path]] = [
            ("baseline", 1, baseline_kml),
            ("moderate_bulk", 50, moderate_kml),
            ("stress_bulk", 200, stress_kml),
            ("massive_polygon", 1, massive_kml),
        ]

        for scenario, aoi_count, source_kml in scenarios:
            print(f"\n=== Scenario: {scenario} ({aoi_count} AOIs) ===")
            scenario_runs: list[RunResult] = []

            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [
                    pool.submit(
                        _run_one,
                        scenario,
                        source_kml,
                        aoi_count,
                        run_id,
                        args.timeout,
                        args.poll_interval,
                        args.container,
                        args.event_grid_function_name,
                        args.event_grid_function_key,
                    )
                    for run_id in range(1, args.runs_per_scenario + 1)
                ]
                for future in as_completed(futures):
                    result = future.result()
                    scenario_runs.append(result)
                    print(
                        f"  run={result.run_id} status={result.runtime_status} "
                        f"duration={result.duration_s:.2f}s instance={result.instance_id}"
                    )

            scenario_runs.sort(key=lambda r: r.run_id)
            all_run_results.extend(scenario_runs)
            summary = _summarize(scenario, aoi_count, scenario_runs)
            summaries.append(summary)
            print(
                f"  summary: success={summary.success_rate:.0%} "
                f"timeouts={summary.timeout_count} p95={summary.duration_p95_s:.2f}s"
            )

    json_report = {
        "generated_at": generated_at,
        "config": {
            "runs_per_scenario": args.runs_per_scenario,
            "concurrency": args.concurrency,
            "timeout_s": args.timeout,
            "poll_interval_s": args.poll_interval,
            "container": args.container,
            "func_base": FUNC_BASE,
        },
        "summaries": [asdict(s) for s in summaries],
        "runs": [asdict(r) for r in all_run_results],
    }

    json_path = output_dir / f"load-baseline-{stamp}.json"
    md_path = output_dir / f"load-baseline-{stamp}.md"

    json_path.write_text(json.dumps(json_report, indent=2, default=str), encoding="utf-8")
    _write_markdown(md_path, summaries, all_run_results, generated_at)

    print("\n=== Baseline complete ===")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")


if __name__ == "__main__":
    main()

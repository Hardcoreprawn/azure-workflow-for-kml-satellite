"""Strict local capacity experiment checks, separate from the smoke oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any

from azure.storage.blob import BlobServiceClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_runner import _upload_ticket

from scripts import e2e_local as harness
from scripts.artifact_validation import validate_artifact_set, validate_content, validate_fixture_outputs
from scripts.capacity_telemetry import build_load_timeline, clock_consistency, collect_timeline, sample_queues
from treesight.constants import LOCAL_AUDIT_MAX_ARTIFACT_BYTES

SAMPLE_INTERVAL_SECONDS = 1.0
READINESS_TIMEOUT_SECONDS = 120.0
WORKER_READINESS_TIMEOUT_SECONDS = 20.0
WORKER_ADDITIONAL_STARTUP_ALLOWANCE_SECONDS = 10.0
WORKER_PROGRESS_INTERVAL_SECONDS = 2.0
READINESS_POLL_INTERVAL_SECONDS = 0.1
EXECUTION_TIMEOUT_SECONDS = 600.0


def profile_environment(workers: int) -> dict[str, str]:
    if workers not in (1, 2, 4):
        raise ValueError("workers must be 1, 2, or 4")
    return {
        "FUNCTIONS_WORKER_PROCESS_COUNT": str(workers),
        "PYTHON_THREADPOOL_THREAD_COUNT": "8",
        "AzureFunctionsJobHost__fileWatchingEnabled": "false",
        "AzureFunctionsJobHost__logging__logLevel__Microsoft.Azure.WebJobs.Script.Workers": "Debug",
        "AzureFunctionsJobHost__logging__logLevel__Worker": "Debug",
        "AzureFunctionsJobHost__extensions__durableTask__maxConcurrentActivityFunctions": "160",
        "AzureFunctionsJobHost__extensions__durableTask__maxConcurrentOrchestratorFunctions": "160",
        "ENRICHMENT_FRAME_CONCURRENCY": "8",
        "ENRICHMENT_CONCURRENCY": "8",
    }


def initialized_worker_count(log: str, *, expected: int | None = None) -> int:
    reused = set(re.findall(r"Found initialized language worker channel for runtime: python workerId:([^\s]+)", log))
    started = log.count("Worker process started and initialized.")
    if expected == 1 and len(reused) == 1 and started == 1:
        return 1
    return len(reused) + started


def workers_ready(log: str, worker_pids: list[int], *, expected: int) -> bool:
    return initialized_worker_count(log, expected=expected) == expected and len(set(worker_pids)) == expected


def assert_complete(result: dict[str, Any], *, parcels: int, images: int) -> None:
    if (
        result.get("status") != "Succeeded"
        or result.get("runtimeStatus") != "Completed"
        or result.get("output", {}).get("status") != "completed"
    ):
        raise ValueError("case did not complete successfully")
    output = result.get("output", {})
    expected = {
        "aoiCount": parcels,
        "featureCount": parcels,
        "metadataCount": parcels,
        "imageryReady": images,
        "downloadsCompleted": images,
        "postProcessCompleted": images,
        "imageryFailed": 0,
        "downloadsFailed": 0,
        "postProcessFailed": 0,
    }
    for field, value in expected.items():
        if output.get(field) != value:
            raise ValueError(f"{field}: expected {value}, got {output.get(field)!r}")
    for field, count in {"metadataPaths": parcels, "rawImageryPaths": images, "clippedImageryPaths": images}.items():
        paths = output.get("artifacts", {}).get(field, [])
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path for path in paths):
            raise ValueError(f"{field}: invalid paths")
        if len(paths) != count or len(set(paths)) != count:
            raise ValueError(f"{field}: expected {count} distinct paths")
    if not output.get("enrichmentManifest"):
        raise ValueError("missing enrichmentManifest")


def process_snapshot() -> list[dict[str, Any]]:
    processes = []
    for directory in Path("/proc").glob("[0-9]*"):
        try:
            arguments = directory.joinpath("cmdline").read_bytes().decode().split("\0")
            fields = directory.joinpath("stat").read_text().rsplit(") ", 1)[1].split()
        except (OSError, UnicodeError, IndexError):
            continue
        if not arguments[0]:
            continue
        processes.append(
            {
                "pid": int(directory.name),
                "worker": any(argument.endswith("/worker.py") for argument in arguments),
                "cpuSeconds": (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK"),
                "rssBytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                "threads": int(fields[17]),
            }
        )
    return processes


def wait_for_workers(log_path: Path, *, expected: int) -> list[int]:
    started = time.monotonic()
    timeout = WORKER_READINESS_TIMEOUT_SECONDS + (expected - 1) * WORKER_ADDITIONAL_STARTUP_ALLOWANCE_SECONDS
    deadline = started + timeout
    pause = Event()
    worker_pids: list[int] = []
    initialized = 0
    previous_state: tuple[tuple[int, ...], int] | None = None
    last_progress = started - WORKER_PROGRESS_INTERVAL_SECONDS
    while (now := time.monotonic()) < deadline:
        worker_pids = [process["pid"] for process in process_snapshot() if process["worker"]]
        log = log_path.read_text(errors="replace")
        initialized = initialized_worker_count(log, expected=expected)
        state = (tuple(sorted(set(worker_pids))), initialized)
        if state != previous_state or now - last_progress >= WORKER_PROGRESS_INTERVAL_SECONDS:
            print(
                f"STARTUP requested={expected} observed={len(set(worker_pids))} initialized={initialized} "
                f"pids={worker_pids} elapsed={now - started:.0f}s timeout={timeout:.0f}s",
                flush=True,
            )
            previous_state = state
            last_progress = now
        if workers_ready(log, worker_pids, expected=expected):
            return worker_pids
        pause.wait(min(READINESS_POLL_INTERVAL_SECONDS, deadline - now))
    raise TimeoutError(
        f"worker startup: requested={expected} observed={len(set(worker_pids))} initialized={initialized}; "
        f"inspect {log_path}"
    )


def sample_processes(stop: Event, samples: list[dict[str, Any]]) -> None:
    previous_pids: list[int] | None = None
    while not stop.is_set():
        processes = process_snapshot()
        samples.append({"time": datetime.now(UTC).isoformat(), "monotonic": time.monotonic(), "processes": processes})
        worker_pids = sorted(process["pid"] for process in processes if process["worker"])
        if worker_pids != previous_pids:
            print(f"WORKERS observed={len(worker_pids)} pids={worker_pids}", flush=True)
            previous_pids = worker_pids
        stop.wait(SAMPLE_INTERVAL_SECONDS)


def verify_artifacts(result: dict[str, Any]) -> int:
    output = result["output"]
    paths = [path for values in output["artifacts"].values() for path in values]
    paths.append(output["enrichmentManifest"])
    with BlobServiceClient.from_connection_string(harness.AZURITE_CONN_STR) as service:
        container = service.get_container_client("kml-output")

        def verify(path: str) -> dict:
            blob = container.get_blob_client(path)
            properties = blob.get_blob_properties()
            if properties.size <= 0:
                raise ValueError(f"empty artifact: {path}")
            if properties.size > LOCAL_AUDIT_MAX_ARTIFACT_BYTES:
                raise ValueError(f"oversized artifact: {path}")
            payload = blob.download_blob(offset=0, length=LOCAL_AUDIT_MAX_ARTIFACT_BYTES + 1).readall()
            if len(payload) != properties.size:
                raise ValueError(f"artifact size changed during validation: {path}")
            return validate_content(path, payload)

        with ThreadPoolExecutor(max_workers=8) as pool:
            documents = dict(zip(paths, pool.map(verify, paths), strict=True))
    validate_artifact_set(output, documents, result["instanceId"])
    validate_fixture_outputs(output, documents, Path(result["inputPath"]))
    return len(paths)


def assert_clean_log(log: str) -> list[str]:
    forbidden = r"NameResolutionError|HTTPSConnectionPool|Retrying \(|Executed 'Functions\.[^']+' \(Failed"
    match = re.search(forbidden, log)
    if match:
        raise ValueError(f"runtime failure or forbidden request evidence: {match.group()}")
    normalized = re.sub(r"(?m)^\[[^\]\n]+\] ", "", log)
    recovered = (
        r"parse_kml_from_blob: Fiona failed for (?P<blob>[^\n]+), falling back to lxml\n"
        r"Traceback \(most recent call last\):\n(?:(?!Traceback).)*?"
        r"fiona.errors.DriverError: unsupported driver: 'KML'\n"
        r"parse_kml_from_blob: lxml parsed features=[1-9][0-9]* blob=(?P=blob)\n"
    )
    remainder, count = re.subn(recovered, "", normalized, flags=re.DOTALL)
    if "Traceback (most recent call last)" in remainder or count > 1:
        raise ValueError("unexpected runtime traceback or repeated parser fallback")
    return ["fiona_kml_driver_unavailable_lxml_fallback"] if count else []


def run_profile(workers: int, parcels: int, directory: Path, *, startup_under_load: bool = False) -> dict[str, Any]:
    environment = profile_environment(workers)
    if parcels not in (50, 200):
        raise ValueError("parcels must be 50 or 200")
    directory.mkdir(parents=True, exist_ok=False)
    manifest = harness.REPO_ROOT / f"tests/fixtures/catalogues/scale-{parcels}.json"
    case = harness.build_representative_case_matrix(manifest)[0]
    _upload_ticket(Path(case["inputPath"]).name, case["container"], user_id="offline-capacity-exercise")
    os.environ.update(environment)
    return execute_profile(case, workers, parcels, directory, environment, startup_under_load=startup_under_load)


def write_observability(directory: Path, report: dict, samples: list[dict], queue_samples: list[dict]) -> None:
    (directory / "queues.json").write_text(json.dumps(queue_samples, indent=2) + "\n")
    observations = report.get("result", {}).get("pollObservations", [])
    (directory / "polls.json").write_text(json.dumps(observations, indent=2) + "\n")
    clock = clock_consistency(samples)
    poll_errors = sum(sample["category"] not in ("status", "not_found") for sample in observations)
    report["measurementQuality"] = {
        "clock": clock,
        "pollSampleCount": len(observations),
        "pollErrorCount": poll_errors,
        "valid": clock["valid"] and bool(observations) and not poll_errors,
    }
    instance_id = report.get("result", {}).get("instanceId")
    if not instance_id:
        raise ValueError("task timeline unavailable: no orchestration instance ID")
    timeline = collect_timeline(
        harness.AZURITE_CONN_STR, (directory / "host.log").read_text(), instance_id, report["startedUtc"]
    )
    timeline["loadTimeline"] = build_load_timeline(timeline["tasks"], samples)
    (directory / "timeline.json").write_text(json.dumps(timeline, indent=2) + "\n")
    report["telemetry"] = {
        "taskCount": len(timeline["tasks"]),
        "missingStartCount": timeline["missingStartCount"],
        "ambiguousStartCount": timeline["ambiguousStartCount"],
        "firstAoiCompletionSeconds": timeline["firstAoiCompletionSeconds"],
        "queueSampleCount": len(queue_samples),
        "missingFinishCount": timeline["missingFinishCount"],
        "ambiguousExecutionCount": timeline["ambiguousExecutionCount"],
        "incompleteTimingCount": timeline["incompleteTimingCount"],
        "complete": bool(timeline["tasks"]) and not timeline["incompleteTimingCount"],
    }
    if any("error" in sample for sample in queue_samples):
        raise ValueError("queue telemetry failed; inspect queues.json")
    if not any(sample.get("queues") for sample in queue_samples):
        raise ValueError("queue telemetry has no queue observations")
    if not report["telemetry"]["complete"]:
        raise ValueError("incomplete task telemetry; inspect timeline.json")
    print(f"TELEMETRY {json.dumps(report['telemetry'])}", flush=True)
    print(f"MEASUREMENT {json.dumps(report['measurementQuality'])}", flush=True)
    if not report["measurementQuality"]["valid"]:
        raise ValueError("measurement quality failed; inspect report.json and polls.json")


def execute_profile(
    case: dict[str, str],
    workers: int,
    parcels: int,
    directory: Path,
    environment: dict[str, str],
    *,
    startup_under_load: bool = False,
) -> dict[str, Any]:
    log_path = directory / "host.log"
    samples: list[dict[str, Any]] = []
    queue_samples: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "workers": workers,
        "startupUnderLoad": startup_under_load,
        "parcels": parcels,
        "environment": environment,
        "python": platform.python_version(),
        "cpuCount": os.cpu_count(),
        "runnerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixtureSha256": hashlib.sha256(Path(case["inputPath"]).read_bytes()).hexdigest(),
        "accepted": False,
        "pollIntervalSeconds": harness.DEFAULT_POLL_INTERVAL_SECONDS,
    }
    stop = Event()
    sampler = Thread(target=sample_processes, args=(stop, samples), daemon=True)
    queue_sampler = Thread(target=sample_queues, args=(stop, queue_samples, harness.AZURITE_CONN_STR), daemon=True)
    report["hostStartUtc"] = datetime.now(UTC).isoformat()
    host = harness.start_func_host(log_path=log_path)
    try:
        harness.wait_for_func_host(
            timeout=READINESS_TIMEOUT_SECONDS,
            interval=READINESS_POLL_INTERVAL_SECONDS,
            progress_interval=WORKER_PROGRESS_INTERVAL_SECONDS,
        )
        report["healthReadyUtc"] = datetime.now(UTC).isoformat()
        if startup_under_load:
            report["workerPids"] = [process["pid"] for process in process_snapshot() if process["worker"]]
        else:
            report["workerPids"] = wait_for_workers(log_path, expected=workers)
        print(
            f"READY requested={workers} pids={report['workerPids']} parcels={parcels} "
            f"startup_under_load={startup_under_load}",
            flush=True,
        )
        sampler.start()
        queue_sampler.start()
        report["startedUtc"] = datetime.now(UTC).isoformat()
        started = time.monotonic()
        result = harness._run_single_case(
            case, timeout=EXECUTION_TIMEOUT_SECONDS, interval=harness.DEFAULT_POLL_INTERVAL_SECONDS
        )
        report.update(result=result, elapsedSeconds=time.monotonic() - started)
        report["finishedUtc"] = datetime.now(UTC).isoformat()
        stop.set()
        sampler.join()
        assert_complete(result, parcels=parcels, images=parcels * 7)
        report["verifiedBlobs"] = verify_artifacts(result)
        report["warnings"] = assert_clean_log(log_path.read_text(errors="replace"))
        final_pids = [process["pid"] for process in process_snapshot() if process["worker"]]
        report["finalWorkerPids"] = final_pids
        observed_pids = set(report["workerPids"]) | {
            process["pid"] for sample in samples for process in sample["processes"] if process["worker"]
        }
        if not observed_pids.issubset(final_pids) or (not startup_under_load and set(final_pids) != observed_pids):
            raise ValueError("worker processes changed during experiment")
        if not workers_ready(log_path.read_text(errors="replace"), final_pids, expected=workers):
            raise ValueError("requested worker pool was not initialized by experiment completion")
        report["accepted"] = True
        return report
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        stop.set()
        if sampler.is_alive():
            sampler.join()
        if queue_sampler.is_alive():
            queue_sampler.join()
        shutdown_error = None
        try:
            harness.stop_func_host(host)
        except Exception as exc:
            report["accepted"] = False
            report["hostShutdownError"] = str(exc)
            shutdown_error = exc
        (directory / "samples.json").write_text(json.dumps(samples))
        telemetry_error = None
        try:
            write_observability(directory, report, samples, queue_samples)
        except Exception as exc:
            report["accepted"] = False
            report["telemetryError"] = str(exc)
            telemetry_error = exc
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        if shutdown_error is not None and "error" not in report:
            raise shutdown_error
        if telemetry_error is not None and "error" not in report:
            raise telemetry_error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--parcels", type=int, choices=(50, 200), default=50)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--startup-under-load", action="store_true")
    args = parser.parse_args()
    report = run_profile(args.workers, args.parcels, args.output, startup_under_load=args.startup_under_load)
    print(f"PASS workers={args.workers} parcels={args.parcels} elapsed={report['elapsedSeconds']:.2f}s", flush=True)


if __name__ == "__main__":
    main()

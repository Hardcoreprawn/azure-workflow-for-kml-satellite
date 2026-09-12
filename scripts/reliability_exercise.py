"""Disposable, milestone-triggered recovery exercise; not a performance benchmark."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Event, Thread
from uuid import uuid4

from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient

from scripts import local_capacity as capacity
from scripts.capacity_telemetry import ACTIVITY_START, HUB_NAME, STORAGE_TIMEOUT_SECONDS
from scripts.local_capacity import harness, process_snapshot


def kill_worker() -> int:
    workers = [process["pid"] for process in process_snapshot() if process["worker"]]
    if len(workers) != 1:
        raise ValueError("worker fault requires exactly one observed Python worker")
    os.kill(workers[0], signal.SIGKILL)
    return workers[0]


def active_download(log: str, instance: str) -> dict[str, str] | None:
    active = {}
    for match in ACTIVITY_START.finditer(log):
        child = match["instance"].removesuffix(":")
        if not child.startswith(instance + ":aoi-") or match["name"] != "download_imagery":
            continue
        identity = (child, match["task"])
        if match["state"] == "started":
            active[identity] = {"instance": child, "task": match["task"]}
        else:
            active.pop(identity, None)
    return next(iter(active.values()), None)


def wait_for_download(path: Path, instance: str, stop: Event) -> dict[str, str]:
    deadline = time.monotonic() + capacity.READINESS_TIMEOUT_SECONDS
    while not stop.is_set() and time.monotonic() < deadline:
        match = active_download(path.read_text(errors="replace") if path.exists() else "", instance)
        if match:
            return match
        stop.wait(capacity.READINESS_POLL_INTERVAL_SECONDS)
    raise TimeoutError("active download milestone not reached")


def wait_for_marker(path: Path, marker: str, stop: Event, *, previous: int = 0) -> None:
    deadline = time.monotonic() + capacity.READINESS_TIMEOUT_SECONDS
    while not stop.is_set() and time.monotonic() < deadline:
        if path.exists() and path.read_text(errors="replace").count(marker) > previous:
            return
        stop.wait(capacity.READINESS_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"fault milestone not reached: {marker}")


def verify_inventory(result: dict) -> None:
    artifacts = result["output"]["artifacts"]
    expected = {path for paths in artifacts.values() for path in paths}
    if result["output"].get("enrichmentManifest"):
        expected.add(result["output"]["enrichmentManifest"])
    project = Path(result["inputPath"]).stem
    prefixes = {
        "/".join(PurePosixPath(path).parts[: PurePosixPath(path).parts.index(project) + 1]) + "/" for path in expected
    }
    with BlobServiceClient.from_connection_string(harness.AZURITE_CONN_STR) as service:
        container = service.get_container_client("kml-output")
        actual = {blob.name for prefix in prefixes for blob in container.list_blobs(name_starts_with=prefix)}
    if actual != expected:
        raise ValueError(
            f"artifact inventory mismatch: extra={len(actual - expected)} missing={len(expected - actual)}"
        )


def execution_ids(instance: str) -> set[str]:
    with TableServiceClient.from_connection_string(
        harness.AZURITE_CONN_STR,
        retry_total=0,
        connection_timeout=STORAGE_TIMEOUT_SECONDS,
        read_timeout=STORAGE_TIMEOUT_SECONDS,
    ) as service:
        rows = service.get_table_client(HUB_NAME + "History").query_entities(
            "PartitionKey eq @instance", parameters={"instance": instance}, select=["ExecutionId"]
        )
        return {row["ExecutionId"] for row in rows if row.get("ExecutionId")}


def exercise_duplicate(
    instance: str, log: Path, url: str, blob: str, length: int, container: str, evidence: dict
) -> None:
    before = execution_ids(instance)
    if len(before) != 1:
        raise ValueError("duplicate baseline must contain exactly one execution")
    evidence["before"] = sorted(before)
    marker = f"Started orchestration instance={instance}"
    count = log.read_text(errors="replace").count(marker)
    harness.fire_event_grid(url, blob, length, container, event_id=instance)
    evidence["applied"] = True
    stop = Event()
    wait_for_marker(log, marker, stop, previous=count)
    evidence["triggerProcessed"] = True
    deadline = time.monotonic() + capacity.READINESS_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        after = execution_ids(instance)
        evidence["after"] = sorted(after)
        if after - before:
            raise ValueError("duplicate event started a second execution generation")
        stop.wait(capacity.READINESS_POLL_INTERVAL_SECONDS)
    raise TimeoutError("duplicate disposition inconclusive: no explicit deduplication evidence")


def run_exercise(fault: str, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    os.environ.update(capacity.profile_environment(1))
    case = harness.build_representative_case_matrix(harness.REPO_ROOT / "tests/fixtures/catalogues/scale-50.json")[0]
    capacity._upload_ticket(Path(case["inputPath"]).name, case["container"], user_id="offline-reliability-exercise")
    report: dict = {"fault": fault, "accepted": False, "injection": {}, "polls": []}
    hosts = []
    stop = Event()
    injector = None
    log = directory / "host.log"
    try:
        hosts.append(harness.start_func_host(log_path=log))
        harness.wait_for_func_host(timeout=capacity.READINESS_TIMEOUT_SECONDS, interval=0.1, progress_interval=2)
        capacity.wait_for_workers(log, expected=1)
        blob_name, blob_url, length = harness.upload_kml(Path(case["inputPath"]), case["container"])
        instance = str(uuid4())
        report["instanceId"] = instance
        harness.fire_event_grid(blob_url, blob_name, length, case["container"], event_id=instance)

        def inject() -> None:
            try:
                milestone = wait_for_download(log, instance, stop)
                report["injection"].update(
                    activity=milestone,
                    utc=datetime.now(UTC).isoformat(),
                    monotonic=time.monotonic(),
                    workersBefore=[process["pid"] for process in process_snapshot() if process["worker"]],
                )
                print(f"FAULT applying={fault} milestone=download_started", flush=True)
                if fault == "worker-kill":
                    report["injection"]["killedPid"] = kill_worker()
                else:
                    harness.stop_func_host(hosts[-1])
                    hosts.append(harness.start_func_host(log_path=directory / "restarted-host.log"))
                    harness.wait_for_func_host(
                        timeout=capacity.READINESS_TIMEOUT_SECONDS, interval=0.1, progress_interval=2
                    )
                report["injection"]["applied"] = True
            except Exception as exc:
                report["injection"]["error"] = str(exc)

        if fault in ("worker-kill", "host-restart"):
            injector = Thread(target=inject)
            injector.start()
        payload = harness.poll_orchestration(
            instance, timeout=capacity.EXECUTION_TIMEOUT_SECONDS, observations=report["polls"]
        )
        if injector:
            stop.set()
            injector.join()
            if not report["injection"].get("applied"):
                raise ValueError("fault was not applied successfully")
            report["injection"]["workersAfter"] = [
                process["pid"] for process in process_snapshot() if process["worker"]
            ]
            report["injection"]["completedUtc"] = datetime.now(UTC).isoformat()
            if fault == "worker-kill" and not set(report["injection"]["workersAfter"]) - set(
                report["injection"]["workersBefore"]
            ):
                raise ValueError("no replacement worker observed")
        result = {
            **case,
            "instanceId": instance,
            "status": "Succeeded" if payload["runtimeStatus"] == "Completed" else "Failed",
            "runtimeStatus": payload["runtimeStatus"],
            "output": payload.get("output", {}),
        }
        report["result"] = result
        capacity.assert_complete(result, parcels=50, images=350)
        report["verifiedBlobs"] = capacity.verify_artifacts(result)
        verify_inventory(result)
        if fault == "duplicate-event":
            exercise_duplicate(instance, log, blob_url, blob_name, length, case["container"], report["injection"])
        report["accepted"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        stop.set()
        if injector:
            injector.join()
        for host in reversed(hosts):
            try:
                harness.stop_func_host(host)
            except Exception as exc:
                report["accepted"] = False
                report.setdefault("shutdownErrors", []).append(str(exc))
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"RELIABILITY accepted={report['accepted']} fault={fault}", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault", choices=("control", "worker-kill", "host-restart", "duplicate-event"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_exercise(args.fault, args.output)


if __name__ == "__main__":
    main()

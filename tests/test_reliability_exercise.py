from __future__ import annotations

import signal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "replay-error",
        "uncorroborated-replay",
        "running",
        "status",
        "parent",
        "child",
        "action",
        "cause",
        "history",
    ],
)
def test_worker_failure_requires_correlated_terminal_evidence(fault: str) -> None:
    from scripts.reliability_exercise import verify_worker_failure

    result = {
        "instanceId": "run",
        "runtimeStatus": "Failed",
        "status": "Failed",
        "customStatus": {
            "phase": "failed",
            "instance_id": "run",
            "failed_child_instance_id": "run:aoi-2",
            "recovery_action": "inspect_failure_then_resubmit",
            "completed_aois": 0,
            "total_aois": 50,
        },
    }
    history = [
        {
            "PartitionKey": "run:aoi-2",
            "EventType": "ExecutionCompleted",
            "OrchestrationStatus": "Failed",
            "Result": "python3 exited with code 137 (0x89)",
        }
    ]
    if fault == "running":
        result["runtimeStatus"] = "Running"
    elif fault == "status":
        result["customStatus"]["phase"] = "per_aoi_pipeline"
    elif fault == "parent":
        result["customStatus"]["instance_id"] = "other"
    elif fault == "child":
        result["customStatus"]["failed_child_instance_id"] = "other:aoi-2"
    elif fault == "action":
        result["customStatus"]["recovery_action"] = None
    elif fault == "cause":
        history[0]["Result"] = "unrelated error"
    elif fault == "history":
        history[0]["PartitionKey"] = "run:aoi-3"
    log = ""
    if fault in ("replay-error", "uncorroborated-replay"):
        history[0]["Result"] = "Non-Deterministic workflow detected: previous execution scheduled an activity"
    if fault == "replay-error":
        log = (
            "Orchestrator function 'aoi_pipeline' failed: One or more errors occurred. "
            "(python exited with code 137 (0x89))."
        )
    if fault == "none":
        verify_worker_failure(result, history, log)
    else:
        with pytest.raises(ValueError):
            verify_worker_failure(result, history, log)


def test_inventory_covers_every_artifact_role(monkeypatch):
    from scripts import reliability_exercise

    paths = [
        "metadata/fixture/t/meta.json",
        "imagery/baseline/fixture/t/a.tif",
        "imagery/framed/fixture/t/a.tif",
        "enrichment/fixture/t/manifest.json",
    ]
    container = MagicMock()
    container.list_blobs.side_effect = lambda name_starts_with: [
        SimpleNamespace(name=path) for path in paths if path.startswith(name_starts_with)
    ]
    service = MagicMock()
    service.__enter__.return_value.get_container_client.return_value = container
    monkeypatch.setattr(reliability_exercise.BlobServiceClient, "from_connection_string", lambda *args: service)
    reliability_exercise.verify_inventory(
        {"inputPath": "fixture.kml", "output": {"artifacts": {"paths": paths[:-1]}, "enrichmentManifest": paths[-1]}}
    )


def test_failure_evidence_keeps_history_and_scopes_partial_inventory(monkeypatch) -> None:
    from scripts import reliability_exercise

    table_service = MagicMock()
    table = table_service.__enter__.return_value.get_table_client.return_value
    table.query_entities.return_value = [{"PartitionKey": "run:aoi-0", "EventType": "ExecutionCompleted"}]
    blob_service = MagicMock()
    container = blob_service.__enter__.return_value.get_container_client.return_value
    container.list_blobs.return_value = [
        SimpleNamespace(name="imagery/fixture/time/raw.tif", size=23),
        SimpleNamespace(name="imagery/other/time/raw.tif", size=12),
    ]
    monkeypatch.setattr(
        reliability_exercise.TableServiceClient, "from_connection_string", lambda *args, **kw: table_service
    )
    monkeypatch.setattr(reliability_exercise.BlobServiceClient, "from_connection_string", lambda *args: blob_service)
    evidence = reliability_exercise.collect_failure_evidence("run", "fixture")
    assert evidence["history"] == [{"PartitionKey": "run:aoi-0", "EventType": "ExecutionCompleted"}]
    assert evidence["partialInventory"] == [{"name": "imagery/fixture/time/raw.tif", "size": 23}]
    assert evidence["inventoryIsTerminal"] is False
    assert table.query_entities.call_args.kwargs["parameters"] == {"lower": "run", "upper": "run;"}


@pytest.mark.parametrize(
    ("fault", "runtime_status", "accepted"),
    [
        ("worker-kill", "Failed", True),
        ("worker-kill", "Completed", True),
        ("control", "Failed", False),
        ("host-restart", "Failed", False),
    ],
)
def test_exercise_accepts_terminal_failure_only_for_worker_kill(
    monkeypatch, tmp_path, fault, runtime_status, accepted
) -> None:
    import json

    from scripts import reliability_exercise as exercise

    monkeypatch.setattr(exercise, "uuid4", lambda: "run")
    monkeypatch.setattr(exercise.capacity, "_upload_ticket", lambda *args, **kw: None)
    monkeypatch.setattr(exercise.capacity, "wait_for_workers", lambda *args, **kw: None)
    monkeypatch.setattr(
        exercise.harness,
        "build_representative_case_matrix",
        lambda *args: [{"inputPath": "fixture.kml", "container": "input"}],
    )

    def start_host(*, log_path):
        log_path.write_text("")
        return MagicMock()

    monkeypatch.setattr(exercise.harness, "start_func_host", start_host)
    stop_host = MagicMock()
    monkeypatch.setattr(exercise.harness, "stop_func_host", stop_host)
    monkeypatch.setattr(exercise.harness, "wait_for_func_host", lambda **kw: None)
    monkeypatch.setattr(exercise.harness, "upload_kml", lambda *args: ("fixture.kml", "url", 1))
    monkeypatch.setattr(exercise.harness, "fire_event_grid", lambda *args, **kw: None)
    monkeypatch.setattr(exercise, "wait_for_download", lambda *args: {"instance": "run:aoi-0", "task": "8"})
    monkeypatch.setattr(exercise, "kill_worker", lambda: 49)
    processes = iter([[{"pid": 49, "worker": True}], [{"pid": 120, "worker": True}]])
    monkeypatch.setattr(exercise, "process_snapshot", lambda: next(processes))
    monkeypatch.setattr(exercise, "Thread", lambda target: SimpleNamespace(start=target, join=lambda: None))
    status = {
        "phase": "failed",
        "instance_id": "run",
        "failed_child_instance_id": "run:aoi-0",
        "completed_aois": 0,
        "total_aois": 50,
        "recovery_action": "inspect_failure_then_resubmit",
    }
    monkeypatch.setattr(
        exercise.harness,
        "poll_orchestration",
        lambda *args, **kw: {"runtimeStatus": runtime_status, "customStatus": status},
    )
    evidence = {
        "history": [
            {
                "PartitionKey": "run:aoi-0",
                "EventType": "ExecutionCompleted",
                "OrchestrationStatus": "Failed",
                "Result": "python exited with code 137",
            }
        ]
    }
    monkeypatch.setattr(exercise, "collect_failure_evidence", lambda *args: evidence)

    def require_completed(result, **kwargs):
        if result["runtimeStatus"] != "Completed":
            raise ValueError("not completed")

    monkeypatch.setattr(exercise.capacity, "assert_complete", require_completed)
    verify = MagicMock(return_value=751)
    monkeypatch.setattr(exercise.capacity, "verify_artifacts", verify)
    inventory = MagicMock()
    monkeypatch.setattr(exercise, "verify_inventory", inventory)
    directory = tmp_path / "evidence"
    if accepted:
        exercise.run_exercise(fault, directory)
    else:
        with pytest.raises(ValueError, match="not completed"):
            exercise.run_exercise(fault, directory)
    report = json.loads((directory / "report.json").read_text())
    assert report["accepted"] is accepted
    assert report["result"]["status"] == ("Succeeded" if runtime_status == "Completed" else "Failed")
    assert verify.call_count == inventory.call_count == int(runtime_status == "Completed")
    assert stop_host.called
    if accepted:
        assert report["outcome"] == (
            "verified_recovery" if runtime_status == "Completed" else "verified_terminal_failure"
        )


def test_active_download_marker_is_instance_scoped_and_not_finished():
    from scripts.reliability_exercise import active_download

    start = (
        "[2026-09-11T01:00:00Z] run:aoi-0: Function 'download_imagery (Activity)' started. "
        "IsReplay: False. TaskEventId: 2"
    )
    assert active_download(start, "other") is None
    assert active_download(start, "run") == {"instance": "run:aoi-0", "task": "2"}
    assert active_download(start + "\n" + start.replace("started.", "completed."), "run") is None


def test_duplicate_probe_rejects_second_execution(monkeypatch, tmp_path) -> None:
    from scripts import reliability_exercise

    log = tmp_path / "host.log"
    log.write_text("Started orchestration instance=run\n")
    generations = iter([{"first"}, {"second"}])
    monkeypatch.setattr(reliability_exercise, "execution_ids", lambda instance: next(generations))

    def deliver(*args, **kwargs):
        with log.open("a") as stream:
            stream.write("Started orchestration instance=run\n")

    monkeypatch.setattr(reliability_exercise.harness, "fire_event_grid", deliver)
    evidence = {}
    with pytest.raises(ValueError, match="second execution"):
        reliability_exercise.exercise_duplicate("run", log, "url", "file", 1, "container", evidence)
    assert evidence["before"] == ["first"]
    assert evidence["after"] == ["second"]


def test_worker_fault_targets_exactly_one_observed_python_worker(monkeypatch):
    from scripts import reliability_exercise

    monkeypatch.setattr(reliability_exercise, "process_snapshot", lambda: [{"pid": 42, "worker": True}])
    kill = MagicMock()
    monkeypatch.setattr(reliability_exercise.os, "kill", kill)
    assert reliability_exercise.kill_worker() == 42
    kill.assert_called_once_with(42, signal.SIGKILL)


@pytest.mark.parametrize(
    "processes", [[], [{"pid": 42, "worker": False}], [{"pid": 42, "worker": True}, {"pid": 43, "worker": True}]]
)
def test_worker_fault_rejects_ambiguous_target(monkeypatch, processes):
    from scripts import reliability_exercise

    monkeypatch.setattr(reliability_exercise, "process_snapshot", lambda: processes)
    kill = MagicMock()
    monkeypatch.setattr(reliability_exercise.os, "kill", kill)
    with pytest.raises(ValueError, match="exactly one"):
        reliability_exercise.kill_worker()
    kill.assert_not_called()

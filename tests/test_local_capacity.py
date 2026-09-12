from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.local_capacity import assert_clean_log, assert_complete, profile_environment, workers_ready


@pytest.fixture
def complete_result() -> dict:
    return {
        "status": "Succeeded",
        "runtimeStatus": "Completed",
        "output": {
            "status": "completed",
            "aoiCount": 2,
            "featureCount": 2,
            "metadataCount": 2,
            "imageryReady": 14,
            "downloadsCompleted": 14,
            "postProcessCompleted": 14,
            "imageryFailed": 0,
            "downloadsFailed": 0,
            "postProcessFailed": 0,
            "enrichmentManifest": "manifest.json",
            "artifacts": {
                "metadataPaths": [f"meta/{index}" for index in range(2)],
                "rawImageryPaths": [f"raw/{index}" for index in range(14)],
                "clippedImageryPaths": [f"clipped/{index}" for index in range(14)],
            },
        },
    }


def test_complete_result_passes_without_mutation(complete_result: dict) -> None:
    original = deepcopy(complete_result)
    assert_complete(complete_result, parcels=2, images=14)
    assert complete_result == original


@pytest.mark.parametrize("startup_under_load", [False, True])
@pytest.mark.parametrize("replaced_worker", [False, True])
@pytest.mark.parametrize("telemetry_failure", [False, True])
@pytest.mark.parametrize("shutdown_failure", [False, True])
def test_submission_during_startup_preserves_worker_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    complete_result: dict,
    startup_under_load: bool,
    replaced_worker: bool,
    telemetry_failure: bool,
    shutdown_failure: bool,
) -> None:
    from scripts import local_capacity

    events = []
    initial = [35] if startup_under_load else [35, 65, 102, 131]
    final = [99 if replaced_worker else 35, 65, 102, 131]
    snapshots = iter([initial, final] if startup_under_load else [final])
    fixture = tmp_path / "fixture.kml"
    fixture.write_text("fixture")
    (tmp_path / "host.log").write_text("Worker process started and initialized.\n" * 4)
    monkeypatch.setattr(local_capacity.harness, "start_func_host", lambda **kwargs: object())

    def stop_func_host(host):
        events.append("stop")
        if shutdown_failure:
            raise RuntimeError("shutdown failed")

    monkeypatch.setattr(local_capacity.harness, "stop_func_host", stop_func_host)
    monkeypatch.setattr(local_capacity.harness, "wait_for_func_host", lambda **kwargs: events.append("health"))
    monkeypatch.setattr(local_capacity, "wait_for_workers", lambda *args, **kwargs: events.append("pool") or initial)
    monkeypatch.setattr(
        local_capacity, "process_snapshot", lambda: [{"pid": pid, "worker": True} for pid in next(snapshots)]
    )
    monkeypatch.setattr(
        local_capacity,
        "Thread",
        lambda **kwargs: SimpleNamespace(
            start=lambda: None,
            join=lambda: None,
            is_alive=lambda: False,
        ),
    )
    monkeypatch.setattr(
        local_capacity.harness, "_run_single_case", lambda *args, **kwargs: events.append("submit") or complete_result
    )
    monkeypatch.setattr(local_capacity, "verify_artifacts", lambda result: 31)

    def write_observability(*args):
        if telemetry_failure:
            raise ValueError("telemetry failed")

    monkeypatch.setattr(local_capacity, "write_observability", write_observability)
    args = ({"inputPath": str(fixture)}, 4, 2, tmp_path, {})
    if replaced_worker:
        with pytest.raises(ValueError, match="worker processes"):
            local_capacity.execute_profile(*args, startup_under_load=startup_under_load)
    elif shutdown_failure:
        with pytest.raises(RuntimeError, match="shutdown failed"):
            local_capacity.execute_profile(*args, startup_under_load=startup_under_load)
    elif telemetry_failure:
        with pytest.raises(ValueError, match="telemetry failed"):
            local_capacity.execute_profile(*args, startup_under_load=startup_under_load)
    else:
        report = local_capacity.execute_profile(*args, startup_under_load=startup_under_load)
        assert report["accepted"]
        assert report["workerPids"] == initial
        assert report["finalWorkerPids"] == final
        assert report["startupUnderLoad"] is startup_under_load
    saved_report = json.loads((tmp_path / "report.json").read_text())
    assert (tmp_path / "samples.json").exists()
    if shutdown_failure:
        assert not saved_report["accepted"]
        assert saved_report["hostShutdownError"] == "shutdown failed"
    if telemetry_failure:
        assert not saved_report["accepted"]
        assert saved_report["telemetryError"] == "telemetry failed"
        if replaced_worker:
            assert "worker processes" in saved_report["error"]
    assert events == (["health", "submit", "stop"] if startup_under_load else ["health", "pool", "submit", "stop"])


@pytest.mark.parametrize("field", ["aoiCount", "postProcessCompleted", "downloadsCompleted", "metadataCount"])
def test_partial_success_is_rejected(complete_result: dict, field: str) -> None:
    complete_result["output"][field] -= 1
    with pytest.raises(ValueError, match=field):
        assert_complete(complete_result, parcels=2, images=14)


@pytest.mark.parametrize("field", ["imageryFailed", "downloadsFailed", "postProcessFailed"])
def test_reported_failure_is_rejected(complete_result: dict, field: str) -> None:
    complete_result["output"][field] = 1
    with pytest.raises(ValueError, match=field):
        assert_complete(complete_result, parcels=2, images=14)


@pytest.mark.parametrize("field", ["rawImageryPaths", "clippedImageryPaths", "metadataPaths"])
def test_duplicate_paths_are_rejected(complete_result: dict, field: str) -> None:
    paths = complete_result["output"]["artifacts"][field]
    paths[-1] = paths[0]
    with pytest.raises(ValueError, match=field):
        assert_complete(complete_result, parcels=2, images=14)


def test_profile_pins_process_threads_and_host_limits() -> None:
    environment = profile_environment(4)
    assert environment["FUNCTIONS_WORKER_PROCESS_COUNT"] == "4"
    assert environment["PYTHON_THREADPOOL_THREAD_COUNT"] == "8"
    assert "languageWorkers__python__processCount__processStartupInterval" not in environment
    assert environment["AzureFunctionsJobHost__fileWatchingEnabled"] == "false"
    assert environment["AzureFunctionsJobHost__extensions__durableTask__maxConcurrentActivityFunctions"] == "160"
    assert profile_environment(1) | {"FUNCTIONS_WORKER_PROCESS_COUNT": "4"} == environment


@pytest.mark.parametrize("count", [0, 3, 16])
def test_unknown_profile_rejected(count: int) -> None:
    with pytest.raises(ValueError):
        profile_environment(count)


def test_readiness_requires_initialized_messages_and_distinct_processes() -> None:
    marker = "Worker process started and initialized.\n"
    assert not workers_ready(marker, [101, 102], expected=2)
    assert not workers_ready(marker * 2, [101, 101], expected=2)
    assert workers_ready(marker * 2, [101, 102], expected=2)
    assert not workers_ready(marker * 3, [101, 102], expected=2)


def test_readiness_includes_reused_initialized_channel() -> None:
    reused = "Found initialized language worker channel for runtime: python workerId:existing-worker\n"
    started = "Worker process started and initialized.\n"
    assert workers_ready(reused + started, [101, 102], expected=2)
    assert not workers_ready(reused + started, [101], expected=2)
    assert not workers_ready(reused + started * 2, [101, 102], expected=2)


def test_single_worker_dispatcher_message_does_not_double_count_reused_channel() -> None:
    log = (
        "Found initialized language worker channel for runtime: python workerId:existing-worker\n"
        "Worker process started and initialized.\n"
    )
    assert workers_ready(log, [101], expected=1)
    assert not workers_ready(log, [101, 102], expected=1)
    assert not workers_ready(log + "Worker process started and initialized.\n", [101], expected=1)


def test_known_recovered_parser_fallback_is_reported() -> None:
    log = (
        "parse_kml_from_blob: Fiona failed for medium_50.kml, falling back to lxml\n"
        "Traceback (most recent call last):\n"
        "  File fiona.py\n"
        "fiona.errors.DriverError: unsupported driver: 'KML'\n"
        "parse_kml_from_blob: lxml parsed features=50 blob=medium_50.kml\n"
    )
    assert assert_clean_log(log) == ["fiona_kml_driver_unavailable_lxml_fallback"]
    with pytest.raises(ValueError):
        assert_clean_log(log + "Traceback (most recent call last):\nValueError: unexpected")
    with pytest.raises(ValueError):
        assert_clean_log(log.replace("  File fiona.py", "  HTTPSConnectionPool failed"))


@pytest.mark.parametrize(
    "failure", ["HTTPSConnectionPool", "NameResolutionError", "Retrying (", "Traceback (most recent call last):"]
)
def test_unexpected_runtime_failures_are_rejected(failure: str) -> None:
    with pytest.raises(ValueError):
        assert_clean_log(failure)


def test_docker_sampler_uses_bounded_nonstreaming_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import capacity_resources

    calls = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        return SimpleNamespace(stdout='{"Name":"canopex-local-exercise-azurite","CPUPerc":"12.00%"}\n')

    monkeypatch.setattr(capacity_resources.subprocess, "run", run)
    samples = capacity_resources.docker_samples()
    assert samples[0]["Name"] == "canopex-local-exercise-azurite"
    assert samples[0]["time"]
    assert "--no-stream" in calls[0][0]
    assert calls[0][1]["timeout"] == 15
    assert calls[0][1]["check"] is True


def test_docker_sampler_rejects_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import capacity_resources

    monkeypatch.setattr(capacity_resources.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=""))
    with pytest.raises(ValueError, match="empty"):
        capacity_resources.docker_samples()


@pytest.mark.parametrize(("workers", "timeout"), [(1, 20), (2, 30), (4, 50)])
def test_worker_wait_reports_progress_and_times_out_promptly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], workers: int, timeout: int
) -> None:
    from scripts import local_capacity

    log_path = tmp_path / "host.log"
    log_path.write_text("")
    clock = iter([0.0, *range(0, timeout + 1, 10)])
    monkeypatch.setattr(local_capacity.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(local_capacity, "process_snapshot", lambda: [])
    monkeypatch.setattr(local_capacity, "Event", lambda: SimpleNamespace(wait=lambda seconds: None))
    with pytest.raises(TimeoutError, match=r"observed=0.*initialized=0"):
        local_capacity.wait_for_workers(log_path, expected=workers)
    with pytest.raises(StopIteration):
        next(clock)
    output = capsys.readouterr().out
    assert f"requested={workers} observed=0 initialized=0" in output
    assert f"timeout={timeout}s" in output


def test_four_workers_ready_after_twenty_seconds_have_startup_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import local_capacity

    log_path = tmp_path / "host.log"
    log_path.write_text("Worker process started and initialized.\n" * 4)
    processes = [{"pid": pid, "worker": True} for pid in (35, 65, 102, 131)]
    snapshots = iter([processes[:2], processes])
    clock = iter([0.0, 0.0, 25.0])
    waits = []
    monkeypatch.setattr(local_capacity.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(local_capacity, "process_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(local_capacity, "Event", lambda: SimpleNamespace(wait=waits.append))
    assert local_capacity.wait_for_workers(log_path, expected=4) == [35, 65, 102, 131]
    assert waits == [0.1]


def test_worker_readiness_advances_without_progress_interval_delay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import local_capacity

    log_path = tmp_path / "host.log"
    log_path.write_text("Worker process started and initialized.\n")
    snapshots = iter([[], [{"pid": 42, "worker": True}]])
    waits = []
    monkeypatch.setattr(local_capacity, "process_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(local_capacity, "Event", lambda: SimpleNamespace(wait=waits.append))
    assert local_capacity.wait_for_workers(log_path, expected=1) == [42]
    assert waits == [0.1]


def test_ready_workers_do_not_wait(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from scripts import local_capacity

    log_path = tmp_path / "host.log"
    log_path.write_text("Worker process started and initialized.\n")
    waits = []
    monkeypatch.setattr(local_capacity, "process_snapshot", lambda: [{"pid": 42, "worker": True}])
    monkeypatch.setattr(local_capacity, "Event", lambda: SimpleNamespace(wait=waits.append))
    assert local_capacity.wait_for_workers(log_path, expected=1) == [42]
    assert waits == []


def test_health_observation_does_not_wait_for_logging_interval(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.local_capacity import harness

    clock = {"now": 0.0}
    responses = iter([503, 503, 200])
    monkeypatch.setattr(harness.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(harness.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))
    monkeypatch.setattr(harness.httpx, "get", lambda *args, **kwargs: SimpleNamespace(status_code=next(responses)))
    harness.wait_for_func_host(timeout=20, interval=0.1, progress_interval=2.0)
    assert clock["now"] == pytest.approx(0.2)
    assert capsys.readouterr().out.count("waiting for func host") == 1

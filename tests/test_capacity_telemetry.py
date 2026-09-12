from __future__ import annotations

import json
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest

from scripts.capacity_telemetry import build_load_timeline, build_timeline, queue_snapshot, sample_queues


def test_timeline_joins_by_instance_and_task_id_not_name() -> None:
    history = [
        {
            "PartitionKey": "run:aoi-0",
            "EventType": "TaskScheduled",
            "EventId": 2,
            "Name": "download",
            "_Timestamp": "2026-09-10T00:00:00+00:00",
        },
        {
            "PartitionKey": "run:aoi-0",
            "EventType": "TaskCompleted",
            "TaskScheduledId": 2,
            "_Timestamp": "2026-09-10T00:00:05+00:00",
        },
        {
            "PartitionKey": "run:aoi-1",
            "EventType": "TaskScheduled",
            "EventId": 2,
            "Name": "download",
            "_Timestamp": "2026-09-10T00:00:01+00:00",
        },
        {
            "PartitionKey": "run:aoi-0",
            "EventType": "ExecutionCompleted",
            "OrchestrationStatus": "Completed",
            "_Timestamp": "2026-09-10T00:00:06+00:00",
        },
    ]
    log = (
        "[2026-09-10T00:00:02.000Z] run:aoi-0: Function 'download (Activity)' started. "
        "IsReplay: False. TaskEventId: 2\n"
        "[2026-09-10T00:00:04.000Z] run:aoi-0: Function 'download (Activity)' completed. "
        "IsReplay: False. TaskEventId: 2\n"
    )
    report = build_timeline(history, log, "run", "2026-09-10T00:00:00+00:00")
    first, second = report["tasks"]
    assert first["scheduleToStartSeconds"] == 2
    assert first["startToCompletionSeconds"] == 3
    assert first["executionWallSeconds"] == 2
    assert first["completionEventLagSeconds"] == 1
    assert second["scheduleToStartSeconds"] is None
    assert report["firstAoiCompletionSeconds"] == 6
    assert report["missingStartCount"] == 1
    assert report["activitySummary"]["download"]["scheduleToStartSeconds"]["count"] == 1
    assert report["activitySummary"]["download"]["executionWallSeconds"]["p95"] == 2
    samples = [{"time": "2026-09-10T00:00:03+00:00", "processes": [{"worker": True}]}]
    load = build_load_timeline(report["tasks"], samples)[0]
    assert load["activeTasks"] == 1
    assert load["unknownStartTasks"] == 1
    assert load["observedWorkerCount"] == 1


def test_load_timeline_distinguishes_backlog_from_execution() -> None:
    tasks = [
        {
            "scheduledUtc": "2026-09-10T00:00:00Z",
            "startedUtc": "2026-09-10T00:00:05Z",
            "finishedUtc": "2026-09-10T00:00:07Z",
            "completedUtc": "2026-09-10T00:00:08Z",
        }
    ]
    samples = [{"time": "2026-09-10T00:00:03Z", "processes": []}]
    load = build_load_timeline(tasks, samples)[0]
    assert load["scheduledNotStartedTasks"] == 1
    assert load["oldestScheduledTaskAgeSeconds"] == 3
    assert load["activeTasks"] == 0


def test_duplicate_starts_are_not_misreported_as_single_execution() -> None:
    history = [
        {
            "PartitionKey": "run",
            "EventType": "TaskScheduled",
            "EventId": 0,
            "Name": "parse",
            "_Timestamp": "2026-09-10T00:00:00+00:00",
        }
    ]
    line = "[2026-09-10T00:00:01Z] run: Function 'parse (Activity)' started. IsReplay: False. TaskEventId: 0\n"
    report = build_timeline(history, line + line, "run", "2026-09-10T00:00:00+00:00")
    assert report["tasks"][0]["startCount"] == 2
    assert report["tasks"][0]["scheduleToStartSeconds"] is None


def test_concatenated_console_records_preserve_task_identity() -> None:
    history = [
        {
            "PartitionKey": "run",
            "EventType": "TaskScheduled",
            "EventId": task_id,
            "Name": "parse",
            "_Timestamp": "2026-09-10T00:00:00Z",
        }
        for task_id in (0, 1)
    ]
    log = "[2026-09-10T00:00:00Z] Response status: 200"
    for task_id in (0, 1):
        log += (
            f"[2026-09-10T00:00:01Z] run: Function 'parse (Activity)' started. IsReplay: False. TaskEventId: {task_id}"
        )
    report = build_timeline(history, log, "run", "2026-09-10T00:00:00Z")
    assert report["missingStartCount"] == 0
    assert all(task["startCount"] == 1 for task in report["tasks"])
    assert all(task["scheduleToStartSeconds"] == 1 for task in report["tasks"])


def test_queue_sampling_only_peeks_and_reports_unknown_age_for_empty_queue() -> None:
    calls = []
    client = SimpleNamespace(
        get_queue_properties=lambda: SimpleNamespace(approximate_message_count=5),
        peek_messages=lambda **kwargs: calls.append(kwargs) or [],
    )
    service = SimpleNamespace(
        list_queues=lambda **kwargs: [SimpleNamespace(name="durablefunctionshub-workitems")],
        get_queue_client=lambda name: client,
    )
    sample = queue_snapshot(service)[0]
    assert calls == [{"max_messages": 32}]
    assert sample["approximateMessageCount"] == 5
    assert sample["visiblePeekCount"] == 0
    assert sample["oldestPeekedMessageAgeSeconds"] is None


def test_queue_age_uses_insertion_time_without_reading_message_payload() -> None:
    service = SimpleNamespace(
        list_queues=lambda **kwargs: [SimpleNamespace(name="durablefunctionshub-control-00")],
        get_queue_client=lambda name: SimpleNamespace(
            get_queue_properties=lambda: SimpleNamespace(approximate_message_count=1),
            peek_messages=lambda **kwargs: [SimpleNamespace(inserted_on=datetime(2026, 1, 1, tzinfo=UTC))],
        ),
    )
    assert queue_snapshot(service)[0]["oldestPeekedMessageAgeSeconds"] > 0


def test_sampler_failure_is_retained(monkeypatch) -> None:
    from scripts import capacity_telemetry

    def fail(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(capacity_telemetry.QueueServiceClient, "from_connection_string", fail)
    samples = []
    sample_queues(Event(), samples, "local")
    assert samples[0]["error"] == "storage unavailable"


def test_reused_task_id_across_executions_is_ambiguous() -> None:
    history = [
        {
            "PartitionKey": "run",
            "EventType": "TaskScheduled",
            "EventId": 0,
            "ExecutionId": execution,
            "Name": "parse",
            "_Timestamp": "2026-09-10T00:00:00+00:00",
        }
        for execution in ("first", "second")
    ]
    log = "[2026-09-10T00:00:01Z] run: Function 'parse (Activity)' started. IsReplay: False. TaskEventId: 0\n"
    report = build_timeline(history, log, "run", "2026-09-10T00:00:00+00:00")
    assert all(task["scheduleToStartSeconds"] is None for task in report["tasks"])


def test_failed_tasks_and_timers_are_retained_without_success_assumption() -> None:
    history = [
        {
            "PartitionKey": "run",
            "EventType": "TaskScheduled",
            "EventId": 0,
            "Name": "parse",
            "_Timestamp": "2026-09-10T00:00:00Z",
        },
        {"PartitionKey": "run", "EventType": "TaskFailed", "TaskScheduledId": 0, "_Timestamp": "2026-09-10T00:00:02Z"},
        {
            "PartitionKey": "run",
            "EventType": "TimerCreated",
            "EventId": 1,
            "_Timestamp": "2026-09-10T00:00:02Z",
            "FireAt": "2026-09-10T00:00:12Z",
        },
    ]
    report = build_timeline(history, "", "run", "2026-09-10T00:00:00Z")
    assert report["tasks"][0]["status"] == "TaskFailed"
    assert report["tasks"][0]["executionWallSeconds"] is None
    assert report["firstAoiCompletionSeconds"] is None
    assert report["timers"] == [history[2]]


@pytest.mark.parametrize("queue_samples", [[], [{"error": "unavailable"}]])
def test_task_evidence_is_saved_even_when_queue_collection_fails(monkeypatch, tmp_path, queue_samples) -> None:
    from scripts import local_capacity

    timeline = build_timeline([], "", "run", "2026-09-10T00:00:00Z")
    monkeypatch.setattr(local_capacity, "collect_timeline", lambda *args: timeline)
    (tmp_path / "host.log").write_text("")
    report = {"result": {"instanceId": "run"}, "startedUtc": "2026-09-10T00:00:00Z"}
    with pytest.raises(ValueError, match="queue telemetry"):
        local_capacity.write_observability(tmp_path, report, [], queue_samples)
    assert json.loads((tmp_path / "timeline.json").read_text())["instanceId"] == "run"
    assert json.loads((tmp_path / "queues.json").read_text()) == queue_samples


@pytest.mark.parametrize("utc_seconds, valid", [([0, 1, 2], True), ([0, 3, 4], False), ([0, 3, 2], False)])
def test_clock_consistency_detects_jumps_even_when_net_drift_cancels(utc_seconds, valid) -> None:
    from scripts import capacity_telemetry

    samples = [
        {"time": f"2026-09-10T00:00:0{seconds}Z", "monotonic": float(index)}
        for index, seconds in enumerate(utc_seconds)
    ]
    result = capacity_telemetry.clock_consistency(samples)
    assert result["valid"] is valid
    assert result["maxOffsetRangeSeconds"] == (0.0 if valid else 2.0)


@pytest.mark.parametrize("samples", [[], [{"time": "2026-09-10T00:00:00Z", "monotonic": 0.0}]])
def test_clock_consistency_requires_multiple_samples(samples) -> None:
    from scripts import capacity_telemetry

    assert capacity_telemetry.clock_consistency(samples)["valid"] is False


@pytest.mark.parametrize("drift", [0, 2])
@pytest.mark.parametrize("category", ["status", "rate_limited"])
def test_measurement_acceptance_requires_stable_clock_and_clean_polls(monkeypatch, tmp_path, drift, category):
    from scripts import local_capacity

    timeline = build_timeline([], "", "run", "2026-09-10T00:00:00Z")
    timeline["tasks"] = [{}]
    monkeypatch.setattr(local_capacity, "collect_timeline", lambda *args: timeline)
    monkeypatch.setattr(local_capacity, "build_load_timeline", lambda *args: [])
    (tmp_path / "host.log").write_text("")
    observations = [{"httpStatus": 200 if category == "status" else 429, "category": category}]
    report = {
        "result": {"instanceId": "run", "pollObservations": observations},
        "startedUtc": "2026-09-10T00:00:00Z",
    }
    samples = [
        {"time": "2026-09-10T00:00:00Z", "monotonic": 0.0},
        {"time": f"2026-09-10T00:00:0{1 + drift}Z", "monotonic": 1.0},
    ]
    if drift or category != "status":
        with pytest.raises(ValueError, match="measurement quality"):
            local_capacity.write_observability(tmp_path, report, samples, [{"queues": [{"name": "workitems"}]}])
    else:
        local_capacity.write_observability(tmp_path, report, samples, [{"queues": [{"name": "workitems"}]}])
    assert report["measurementQuality"]["clock"]["valid"] is (drift == 0)
    assert report["measurementQuality"]["pollErrorCount"] == (category != "status")
    assert report["measurementQuality"]["valid"] is (drift == 0 and category == "status")
    assert (tmp_path / "timeline.json").exists()
    assert json.loads((tmp_path / "polls.json").read_text()) == observations


def test_partial_trace_is_retained_but_not_accepted(monkeypatch, tmp_path) -> None:
    from scripts import local_capacity

    history = [
        {
            "PartitionKey": "run",
            "EventType": "TaskScheduled",
            "EventId": 0,
            "Name": "parse",
            "_Timestamp": "2026-09-10T00:00:00Z",
        }
    ]
    timeline = build_timeline(history, "", "run", "2026-09-10T00:00:00Z")
    monkeypatch.setattr(local_capacity, "collect_timeline", lambda *args: timeline)
    (tmp_path / "host.log").write_text("")
    report = {"result": {"instanceId": "run"}, "startedUtc": "2026-09-10T00:00:00Z"}
    with pytest.raises(ValueError, match="incomplete task telemetry"):
        local_capacity.write_observability(tmp_path, report, [], [{"queues": [{"name": "workitems"}]}])
    assert (tmp_path / "timeline.json").exists()
    assert report["telemetry"]["complete"] is False


@pytest.mark.parametrize(
    ("scheduled", "completed", "completion_count"),
    [
        (3, 4, 1),
        (0, 1, 1),
        (0, 4, 0),
        (0, 4, 2),
    ],
)
def test_invalid_or_unresolved_timing_is_incomplete(scheduled, completed, completion_count) -> None:
    history = [
        {
            "PartitionKey": "run",
            "EventType": "TaskScheduled",
            "EventId": 0,
            "Name": "parse",
            "_Timestamp": f"2026-09-10T00:00:0{scheduled}Z",
        }
    ]
    history += [
        {
            "PartitionKey": "run",
            "EventType": "TaskCompleted",
            "TaskScheduledId": 0,
            "_Timestamp": f"2026-09-10T00:00:0{completed}Z",
        }
        for _ in range(completion_count)
    ]
    log = (
        "[2026-09-10T00:00:01Z] run: Function 'parse (Activity)' started. IsReplay: False. TaskEventId: 0\n"
        "[2026-09-10T00:00:02Z] run: Function 'parse (Activity)' completed. IsReplay: False. TaskEventId: 0\n"
    )
    assert build_timeline(history, log, "run", "2026-09-10T00:00:00Z")["incompleteTimingCount"] == 1

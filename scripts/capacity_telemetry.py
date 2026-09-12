"""Read-only local Durable timing and queue evidence for capacity experiments."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from itertools import pairwise
from math import ceil
from threading import Event
from typing import Any

from azure.data.tables import TableServiceClient
from azure.storage.queue import QueueServiceClient

HUB_NAME = "DurableFunctionsHub"
QUEUE_SAMPLE_INTERVAL_SECONDS = 2.0
QUEUE_PEEK_LIMIT = 32
STORAGE_TIMEOUT_SECONDS = 3
MAX_CLOCK_DRIFT_SECONDS = 0.1
HISTORY_FIELDS = (
    "PartitionKey",
    "RowKey",
    "ExecutionId",
    "EventType",
    "EventId",
    "TaskScheduledId",
    "Name",
    "_Timestamp",
    "FireAt",
    "TimerId",
    "OrchestrationStatus",
)
ACTIVITY_START = re.compile(
    r"\[(?P<time>\d{4}-\d{2}-\d{2}T[^\]]+)\] (?P<instance>\S+): Function '(?P<name>[^']+) \(Activity\)' "
    r"(?P<state>started|completed|failed)\. "
    r"(?:(?!\[\d{4}-\d{2}-\d{2}T)[^\n])*?IsReplay: False\."
    r"(?:(?!\[\d{4}-\d{2}-\d{2}T)[^\n])*?TaskEventId: (?P<task>\d+)",
    re.MULTILINE,
)


def timestamp(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("telemetry timestamp must include timezone")
    return parsed


def clock_consistency(samples: list[dict]) -> dict[str, Any]:
    offsets = [timestamp(sample["time"]).timestamp() - sample["monotonic"] for sample in samples]
    spread = max(offsets) - min(offsets) if offsets else None
    ordered = all(right["monotonic"] > left["monotonic"] for left, right in pairwise(samples))
    return {
        "sampleCount": len(samples),
        "maxOffsetRangeSeconds": round(spread, 6) if spread is not None else None,
        "toleranceSeconds": MAX_CLOCK_DRIFT_SECONDS,
        "valid": len(samples) >= 2 and ordered and spread is not None and spread <= MAX_CLOCK_DRIFT_SECONDS,
    }


def seconds_between(start: Any, finish: Any) -> float | None:
    if start is None or finish is None:
        return None
    duration = (timestamp(finish) - timestamp(start)).total_seconds()
    return round(duration, 6) if duration >= 0 else None


def task_record(row: dict, history: list[dict], starts: dict, finishes: dict) -> dict[str, Any]:
    instance, task_id = row["PartitionKey"], row["EventId"]
    matches = starts.get((instance, int(task_id)), [])
    endings = finishes.get((instance, int(task_id)), [])
    generations = {
        event.get("ExecutionId")
        for event in history
        if event.get("PartitionKey") == instance
        and event.get("EventType") == "TaskScheduled"
        and event.get("EventId") == task_id
    }
    completed = [
        event
        for event in history
        if event.get("PartitionKey") == instance
        and event.get("ExecutionId") == row.get("ExecutionId")
        and event.get("TaskScheduledId") == task_id
        and event.get("EventType") in ("TaskCompleted", "TaskFailed")
    ]
    start = matches[0] if len(matches) == 1 and len(generations) == 1 else None
    finish = endings[0] if len(endings) == 1 and start is not None else None
    end = str(completed[0]["_Timestamp"]) if len(completed) == 1 else None
    scheduled = str(row["_Timestamp"])
    return {
        "instanceId": instance,
        "taskId": task_id,
        "executionId": row.get("ExecutionId"),
        "name": row["Name"],
        "scheduledUtc": scheduled,
        "startedUtc": start,
        "completedUtc": end,
        "startCount": len(matches),
        "status": completed[0]["EventType"] if len(completed) == 1 else "unresolved",
        "scheduleToStartSeconds": seconds_between(scheduled, start),
        "startToCompletionSeconds": seconds_between(start, end),
        "finishedUtc": finish,
        "ambiguousExecution": len(generations) != 1,
        "executionWallSeconds": seconds_between(start, finish),
        "completionEventLagSeconds": seconds_between(finish, end),
    }


def build_timeline(history: list[dict], log: str, instance_id: str, started_utc: str) -> dict[str, Any]:
    events = [
        row
        for row in history
        if row.get("PartitionKey") == instance_id or str(row.get("PartitionKey", "")).startswith(instance_id + ":aoi-")
    ]
    starts: dict[tuple[str, int], list[str]] = {}
    finishes: dict[tuple[str, int], list[str]] = {}
    for match in ACTIVITY_START.finditer(log):
        target = starts if match["state"] == "started" else finishes
        target.setdefault((match["instance"], int(match["task"])), []).append(match["time"])
    tasks = [task_record(row, events, starts, finishes) for row in events if row.get("EventType") == "TaskScheduled"]
    completions = [
        str(row["_Timestamp"])
        for row in events
        if row.get("EventType") == "ExecutionCompleted"
        and row.get("OrchestrationStatus") == "Completed"
        and row["PartitionKey"].startswith(instance_id + ":aoi-")
    ]
    first = min(completions, key=timestamp) if completions else None
    return {
        "schemaVersion": 1,
        "instanceId": instance_id,
        "tasks": tasks,
        "activitySummary": activity_summary(tasks),
        "longestQueueDelays": sorted(
            (task for task in tasks if task["scheduleToStartSeconds"] is not None),
            key=lambda task: task["scheduleToStartSeconds"],
            reverse=True,
        )[:10],
        "firstAoiCompletionUtc": first,
        "firstAoiCompletionSeconds": seconds_between(started_utc, first),
        "aoiCompletionCount": len(completions),
        "missingStartCount": sum(task["startCount"] == 0 for task in tasks),
        "ambiguousStartCount": sum(task["startCount"] > 1 for task in tasks),
        "ambiguousExecutionCount": sum(task["ambiguousExecution"] for task in tasks),
        "missingFinishCount": sum(task["finishedUtc"] is None for task in tasks),
        "incompleteTimingCount": sum(
            any(
                task[field] is None
                for field in ("scheduleToStartSeconds", "executionWallSeconds", "completionEventLagSeconds")
            )
            for task in tasks
        ),
        "timers": [row for row in events if row.get("EventType") in ("TimerCreated", "TimerFired")],
    }


def activity_summary(tasks: list[dict]) -> dict:
    summary = {}
    for name in sorted({task["name"] for task in tasks}):
        selected = [task for task in tasks if task["name"] == name]
        fields = {}
        for field in ("scheduleToStartSeconds", "executionWallSeconds", "completionEventLagSeconds"):
            values = sorted(task[field] for task in selected if task[field] is not None)
            fields[field] = {
                "count": len(values),
                "p50": values[ceil(len(values) * 0.5) - 1] if values else None,
                "p95": values[ceil(len(values) * 0.95) - 1] if values else None,
                "max": max(values) if values else None,
            }
        summary[name] = {"taskCount": len(selected), **fields}
    return summary


def build_load_timeline(tasks: list[dict], samples: list[dict]) -> list[dict]:
    aligned = []
    for sample in samples:
        observed = timestamp(sample["time"])
        scheduled = [task for task in tasks if timestamp(task["scheduledUtc"]) <= observed]
        pending = [task for task in scheduled if task["startedUtc"] and timestamp(task["startedUtc"]) > observed]
        active = [
            task
            for task in scheduled
            if task["startedUtc"]
            and task["finishedUtc"]
            and timestamp(task["startedUtc"]) <= observed < timestamp(task["finishedUtc"])
        ]
        unresolved = [
            task for task in scheduled if not task["completedUtc"] or timestamp(task["completedUtc"]) > observed
        ]
        aligned.append(
            {
                "time": sample["time"],
                "activeTasks": len(active),
                "scheduledNotStartedTasks": len(pending),
                "unknownStartTasks": sum(task["startedUtc"] is None for task in unresolved),
                "unknownFinishTasks": sum(task["finishedUtc"] is None for task in unresolved),
                "oldestScheduledTaskAgeSeconds": max(
                    (seconds_between(task["scheduledUtc"], sample["time"]) for task in pending), default=None
                ),
                "observedWorkerCount": sum(process["worker"] for process in sample["processes"]),
            }
        )
    return aligned


def collect_timeline(connection: str, log: str, instance_id: str, started_utc: str) -> dict[str, Any]:
    with TableServiceClient.from_connection_string(
        connection,
        retry_total=0,
        connection_timeout=STORAGE_TIMEOUT_SECONDS,
        read_timeout=STORAGE_TIMEOUT_SECONDS,
    ) as service:
        table = service.get_table_client(HUB_NAME + "History")
        query = "PartitionKey ge @lower and PartitionKey lt @upper"
        rows = list(
            table.query_entities(
                query, parameters={"lower": instance_id, "upper": instance_id + ";"}, select=list(HISTORY_FIELDS)
            )
        )
    safe_rows = [
        {
            key: str(value) if isinstance(value, datetime) else value
            for key, value in row.items()
            if key in HISTORY_FIELDS
        }
        for row in rows
    ]
    timeline = build_timeline(safe_rows, log, instance_id, started_utc)
    timeline["history"] = safe_rows
    if not timeline["tasks"]:
        raise ValueError("no scheduled tasks found in Durable history")
    return timeline


def queue_snapshot(service: QueueServiceClient) -> list[dict[str, Any]]:
    snapshots = []
    for queue in service.list_queues(name_starts_with=HUB_NAME.lower() + "-"):
        client = service.get_queue_client(queue.name)
        properties = client.get_queue_properties()
        messages = list(client.peek_messages(max_messages=QUEUE_PEEK_LIMIT))
        observed = datetime.now(UTC)
        oldest = min((message.inserted_on for message in messages), default=None)
        snapshots.append(
            {
                "name": queue.name,
                "time": observed.isoformat(),
                "approximateMessageCount": properties.approximate_message_count,
                "visiblePeekCount": len(messages),
                "peekLimit": QUEUE_PEEK_LIMIT,
                "oldestPeekedMessageAgeSeconds": seconds_between(oldest, observed),
            }
        )
    return snapshots


def sample_queues(stop: Event, samples: list[dict], connection: str) -> None:
    try:
        with QueueServiceClient.from_connection_string(
            connection,
            retry_total=0,
            connection_timeout=STORAGE_TIMEOUT_SECONDS,
            read_timeout=STORAGE_TIMEOUT_SECONDS,
        ) as service:
            while not stop.is_set():
                started = time.monotonic()
                queues = queue_snapshot(service)
                samples.append(
                    {
                        "time": datetime.now(UTC).isoformat(),
                        "queues": queues,
                        "collectionSeconds": time.monotonic() - started,
                    }
                )
                stop.wait(QUEUE_SAMPLE_INTERVAL_SECONDS)
    except Exception as exc:
        samples.append({"time": datetime.now(UTC).isoformat(), "error": str(exc)})

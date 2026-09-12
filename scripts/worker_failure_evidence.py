"""Conservative, read-only correlation of isolated worker-exit evidence."""

from __future__ import annotations

import re

from scripts.capacity_telemetry import timestamp
from treesight.constants import LOCAL_AUDIT_WORKER_CORRELATION_SECONDS


def _failed_invocations(log: str) -> list[dict]:
    starts = list(re.finditer(r"\[(?P<time>[^\]]+)\] Executing 'Functions.aoi_pipeline' [^\n]*Id=(?P<id>[^)]+)\)", log))
    failures = re.finditer(
        r"\[(?P<time>[^\]]+)\] Executed 'Functions.aoi_pipeline' \(Failed, Id=(?P<id>[^,]+),[^\n]*\n"
        r"\[[^\]]+\] [^\n]*Orchestrator function 'aoi_pipeline' failed:[^\n]*python3? exited with code 137",
        log,
    )
    return [
        {"id": failure["id"], "start": timestamp(matches[0]["time"]), "end": timestamp(failure["time"])}
        for failure in failures
        if len(matches := [start for start in starts if start["id"] == failure["id"]]) == 1
    ]


def correlate_worker_exit(child: str, history: list[dict], log: str, injection: dict) -> dict:
    events = [row for row in history if row.get("PartitionKey") == child and row.get("EventType")]
    generations = {row.get("ExecutionId") for row in events}
    failures = [
        row
        for row in events
        if row.get("EventType") == "ExecutionCompleted" and row.get("OrchestrationStatus") == "Failed"
    ]
    if len(generations) != 1 or None in generations or len(failures) != 1:
        raise ValueError("worker failure requires one failed child execution")
    ended = timestamp(failures[0]["_Timestamp"])
    starts = [timestamp(row["_Timestamp"]) for row in events if row["EventType"] == "OrchestratorStarted"]
    if not starts or not injection.get("utc") or not injection.get("killedPid"):
        raise ValueError("worker failure lacks replay/injection evidence")
    started, killed = max(starts), timestamp(injection["utc"])
    tolerance = LOCAL_AUDIT_WORKER_CORRELATION_SECONDS
    candidates = [
        invocation
        for invocation in _failed_invocations(log)
        if abs((invocation["start"] - started).total_seconds()) <= tolerance
        and abs((invocation["end"] - ended).total_seconds()) <= tolerance
        and invocation["start"] <= killed <= invocation["end"]
    ]
    peers = [
        row
        for row in history
        if row.get("PartitionKey") != child
        and row.get("EventType") == "ExecutionCompleted"
        and row.get("OrchestrationStatus") == "Failed"
        and any(
            abs((timestamp(row["_Timestamp"]) - invocation["end"]).total_seconds()) <= tolerance
            for invocation in candidates
        )
    ]
    exits = re.finditer(
        rf"\[(?P<time>[^\]]+)\] Language Worker Process exited\. Pid={int(injection['killedPid'])}\.", log
    )
    worker_exited = any(killed <= timestamp(match["time"]) <= ended for match in exits)
    if len(candidates) != 1 or peers or not worker_exited:
        raise ValueError("worker failure invocation correlation is missing or ambiguous")
    return {
        "childInstanceId": child,
        "executionId": next(iter(generations)),
        "invocationId": candidates[0]["id"],
        "killedPid": injection["killedPid"],
    }

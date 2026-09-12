from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "other-child",
        "stale-execution",
        "late-kill",
        "other-pid",
        "unrelated-error",
        "ambiguous",
        "offset-ambiguity",
    ],
)
def test_worker_exit_requires_unique_child_replay_and_invocation(fault: str) -> None:
    from scripts.worker_failure_evidence import correlate_worker_exit

    history = [
        {
            "PartitionKey": "run:aoi-2",
            "ExecutionId": "execution",
            "EventType": "OrchestratorStarted",
            "_Timestamp": "2026-09-12T18:45:21.202196+00:00",
        },
        {
            "PartitionKey": "run:aoi-2",
            "ExecutionId": "execution",
            "EventType": "ExecutionCompleted",
            "OrchestrationStatus": "Failed",
            "_Timestamp": "2026-09-12T18:45:21.564580+00:00",
        },
    ]
    log = (
        "[2026-09-12T18:45:21.203Z] Executing 'Functions.aoi_pipeline' (Reason='(null)', Id=invocation)\n"
        "[2026-09-12T18:45:21.508Z] Language Worker Process exited. Pid=49.\n"
        "[2026-09-12T18:45:21.562Z] Executed 'Functions.aoi_pipeline' (Failed, Id=invocation, Duration=359ms)\n"
        "[2026-09-12T18:45:21.562Z] Orchestrator function 'aoi_pipeline' failed: "
        "One or more errors occurred. (python exited with code 137 (0x89)).\n"
    )
    injection = {"utc": "2026-09-12T18:45:21.485583+00:00", "killedPid": 49}
    if fault == "other-child":
        history = [{**row, "PartitionKey": "other:aoi-2"} for row in history]
    elif fault == "stale-execution":
        history = [*history, {**history[0], "ExecutionId": "stale"}]
    elif fault == "late-kill":
        injection = {**injection, "utc": "2026-09-12T18:46:21+00:00"}
    elif fault == "other-pid":
        injection = {**injection, "killedPid": 999}
    elif fault == "unrelated-error":
        log = log.replace("python exited with code 137", "unrelated runtime error")
    elif fault == "ambiguous":
        history = [*history, {**history[1], "PartitionKey": "run:aoi-3"}]
    elif fault == "offset-ambiguity":
        history = [
            history[0],
            {**history[1], "_Timestamp": "2026-09-12T18:45:21.660+00:00"},
            {**history[1], "PartitionKey": "run:aoi-3", "_Timestamp": "2026-09-12T18:45:21.558+00:00"},
        ]
    if fault == "none":
        assert correlate_worker_exit("run:aoi-2", history, log, injection) == {
            "childInstanceId": "run:aoi-2",
            "executionId": "execution",
            "invocationId": "invocation",
            "killedPid": 49,
        }
    else:
        with pytest.raises(ValueError):
            correlate_worker_exit("run:aoi-2", history, log, injection)

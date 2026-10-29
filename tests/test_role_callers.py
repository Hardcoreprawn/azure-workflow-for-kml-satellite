"""Admission caller routing is part of the role-boundary contract."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import dev_event_grid_relay
import dev_server
import e2e_local
import pytest
import simulate_upload
import ux_journeys
import yaml

from scripts import local_capacity

ROOT = Path(__file__).resolve().parents[1]


def test_business_callers_default_to_admission():
    assert simulate_upload.FUNC_BASE == "http://localhost:7072"
    assert e2e_local.FUNC_BASE == "http://localhost:7072"
    assert ux_journeys.DEFAULT_FUNC_BASE == "http://localhost:7072"
    assert dev_server.DevProxyHandler.func_origin == "http://localhost:7072"
    assert dev_event_grid_relay.DEFAULT_FUNC_BASE == "http://orch:80"


def test_compose_proxy_and_relay_use_admission():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    assert "--func-host orch" in services["web"]["command"]
    assert services["event-grid-relay"]["command"][-1] == "http://orch:80"
    assert "orch" in services["event-grid-relay"]["depends_on"]
    assert services["orch"]["environment"]["AzureFunctionsWebHost__hostid"] == "canopex-local-admission"
    assert services["event-grid-relay"]["environment"]["ADMISSION_HOST_ID"] == "canopex-local-admission"


def test_effective_devcontainer_smoke_targets_admission():
    config = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
    environment = {}
    for filename in config["dockerComposeFile"]:
        layer = yaml.safe_load((ROOT / ".devcontainer" / filename).read_text())
        environment.update(layer["services"].get(config["service"], {}).get("environment", {}))
    environment.update(config.get("remoteEnv", {}))
    result = subprocess.run(
        [
            "bash",
            "-c",
            """curl() { printf '%s\\n' '{"status":"healthy"}'; }; export -f curl; make SHELL=bash smoke""",
        ],
        cwd=ROOT,
        env={**os.environ, "FUNC_URL": environment["FUNC_URL"]},
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert "Smoke-checking http://orch:80/api/health/deep" in result.stdout


def test_offline_gate_starts_separate_admission_and_worker(monkeypatch):
    calls = []

    def start(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(e2e_local, "_start_role_host", start)
    hosts = e2e_local.start_func_host(log_path=ROOT / ".unused.log")
    assert len(hosts) == 2
    assert {call["role"] for call in calls} == {"compute", "orchestrator"}
    assert len({call["port"] for call in calls}) == 2
    assert len({call["log_path"] for call in calls}) == 2


def test_capacity_counts_compute_workers_not_admission():
    arguments = ["python", "/runtime/worker.py"]
    assert local_capacity.is_compute_worker(arguments, b"PIPELINE_ROLE=full\0")
    assert not local_capacity.is_compute_worker(arguments, b"PIPELINE_ROLE=orchestrator\0")
    assert not local_capacity.is_compute_worker(["python", "other.py"], b"PIPELINE_ROLE=full\0")


def test_local_role_environments_preserve_shared_storage_and_separate_secrets():
    worker = e2e_local.build_func_host_env({"FUNCTIONS_WORKER_PROCESS_COUNT": "4"}, role="compute")
    admission = e2e_local.build_func_host_env({"FUNCTIONS_WORKER_PROCESS_COUNT": "4"}, role="orchestrator")
    assert worker["AzureWebJobsStorage"] == admission["AzureWebJobsStorage"]
    assert worker["PIPELINE_ROLE"] == "full"
    assert admission["PIPELINE_ROLE"] == "orchestrator"
    assert worker["PYTHON_SCRIPT_FILE_NAME"] == "function_app.py"
    assert admission["PYTHON_SCRIPT_FILE_NAME"] == "function_app_orch.py"
    assert worker["FUNCTIONS_SECRETS_PATH"] != admission["FUNCTIONS_SECRETS_PATH"]
    assert worker["AzureFunctionsWebHost__hostid"] != admission["AzureFunctionsWebHost__hostid"]
    assert worker["FUNCTIONS_WORKER_PROCESS_COUNT"] == "4"
    assert admission["FUNCTIONS_WORKER_PROCESS_COUNT"] == "1"


def test_relay_reads_only_configured_admission_secret(monkeypatch):
    service = MagicMock()
    container = service.get_container_client.return_value
    container.get_blob_client.return_value.download_blob.return_value.readall.return_value = (
        b'{"systemKeys":[{"name":"eventgrid_extension","value":"local-key"}]}'
    )
    monkeypatch.setattr(dev_event_grid_relay, "ADMISSION_HOST_ID", "owned-admission")
    assert dev_event_grid_relay._fetch_eventgrid_key(service, retries=1) == "local-key"
    container.get_blob_client.assert_called_once_with("owned-admission/host.json")
    container.list_blobs.assert_not_called()


def test_relay_does_not_fall_back_to_worker_keys(monkeypatch):
    service = MagicMock()
    container = service.get_container_client.return_value
    container.get_blob_client.return_value.download_blob.side_effect = RuntimeError("unavailable")
    monkeypatch.setattr(dev_event_grid_relay, "ADMISSION_HOST_ID", "missing-admission")
    assert dev_event_grid_relay._fetch_eventgrid_key(service, retries=1) is None
    container.list_blobs.assert_not_called()


def test_offline_gate_rejects_occupied_ports(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value.connect_ex.return_value = 0
    monkeypatch.setattr(e2e_local.socket, "socket", lambda: connection)
    start = MagicMock()
    monkeypatch.setattr(e2e_local, "_start_role_host", start)
    with pytest.raises(RuntimeError, match="owned free port"):
        e2e_local.start_func_host(log_path=ROOT / ".unused.log")
    start.assert_not_called()


def test_offline_gate_cleans_worker_when_admission_start_fails(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value.connect_ex.return_value = 1
    monkeypatch.setattr(e2e_local.socket, "socket", lambda: connection)
    worker = MagicMock()
    monkeypatch.setattr(e2e_local, "_start_role_host", MagicMock(side_effect=[worker, OSError("start failed")]))
    stop = MagicMock()
    monkeypatch.setattr(e2e_local, "_stop_role_host", stop)
    with pytest.raises(OSError, match="start failed"):
        e2e_local.start_func_host(log_path=ROOT / ".unused.log")
    stop.assert_called_once_with(worker)


@pytest.mark.parametrize("failure_point", ["terminate", "kill", "wait"])
def test_shutdown_failure_still_attempts_both_owned_hosts(failure_point):
    worker, admission = MagicMock(), MagicMock()
    worker.poll.return_value = admission.poll.return_value = None
    failure = OSError(f"{failure_point} failed")
    if failure_point == "terminate":
        admission.terminate.side_effect = failure
    elif failure_point == "kill":
        admission.wait.side_effect = subprocess.TimeoutExpired("func", 10)
        admission.kill.side_effect = failure
    else:
        admission.wait.side_effect = [subprocess.TimeoutExpired("func", 10), failure]

    with pytest.raises(ExceptionGroup, match="host shutdown") as raised:
        e2e_local.stop_func_host((worker, admission))
    assert raised.value.exceptions == (failure,)
    admission.terminate.assert_called_once()
    worker.terminate.assert_called_once()
    worker.wait.assert_called_once_with(timeout=10.0)

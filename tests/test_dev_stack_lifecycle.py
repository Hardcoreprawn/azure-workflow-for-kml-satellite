"""Contracts for the local editor and sibling-container lifecycle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_editor_owns_compose_shutdown() -> None:
    config = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
    assert config["shutdownAction"] == "stopCompose"
    assert config["service"] == "devcontainer"
    assert "runServices" not in config
    assert config["remoteUser"] != "root"
    assert config["remoteEnv"]["HOME"] == "/home/vscode"
    assert config["remoteEnv"]["DEV_WORKSPACE"] == "${localWorkspaceFolder}"
    assert config["postStartCommand"] == "bash scripts/dev_stack.sh up"
    assert "mounts" not in config


@pytest.mark.parametrize("service", ["func", "orch"])
def test_functions_wait_for_storage_initialization(service: str) -> None:
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert config["services"][service]["depends_on"]["init-storage"] == {"condition": "service_completed_successfully"}


def test_default_stack_does_not_require_nvidia_or_restart_after_shutdown() -> None:
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for service in config["services"].values():
        assert "runtime" not in service
        assert "container_name" not in service
        assert service.get("restart", "no") == "no"


def test_normal_lifecycle_never_kills_port_owners() -> None:
    makefile = (ROOT / "Makefile").read_text()
    assert "_free-ports" not in makefile
    assert "fuser" not in makefile


@pytest.fixture
def docker_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "docker.jsonl"
    docker = tmp_path / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "with Path(os.environ['DOCKER_CALL_LOG']).open('a') as output:\n"
        "    output.write(json.dumps(args) + '\\n')\n"
        "if args[0] == 'info':\n"
        "    sys.exit(int(os.environ.get('DOCKER_INFO_EXIT', '0')))\n"
        "if args[-2:] == ['config', '--services']:\n"
        "    print('azurite\\ninit-storage\\ncosmos\\nfunc\\norch\\nevent-grid-relay\\nweb\\nollama\\ndevcontainer')\n"
        "if 'up' in args:\n"
        "    sys.exit(int(os.environ.get('DOCKER_UP_EXIT', '0')))\n"
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_CALL_LOG", str(log))
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "lifecycle-test")
    monkeypatch.delenv("CANOPEX_DEVCONTAINER", raising=False)
    monkeypatch.delenv("DEV_WORKSPACE", raising=False)
    return log


def run_stack(action: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "scripts/dev_stack.sh"), action],
        text=True,
        capture_output=True,
        check=False,
    )


def docker_calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_start_waits_and_reuses_images(docker_environment: Path) -> None:
    result = run_stack("up")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(docker_environment)
    start = next(call for call in calls if "up" in call)
    assert "--wait" in start
    assert "--wait-timeout" in start
    assert "--build" not in start
    assert "devcontainer" not in start
    assert not any("down" in call or "build" in call for call in calls)
    assert "lifecycle-test" in start


def test_failed_start_cleans_up_and_keeps_failure(docker_environment: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_UP_EXIT", "17")
    result = run_stack("up")
    assert result.returncode == 17, result.stderr
    calls = docker_calls(docker_environment)
    assert any("logs" in call for call in calls)
    assert any("down" in call for call in calls)
    assert not any("--volumes" in call for call in calls)


def test_editor_shutdown_keeps_editor_alive(docker_environment: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANOPEX_DEVCONTAINER", "1")
    monkeypatch.setenv("DEV_WORKSPACE", "/host/workspace with spaces")
    result = run_stack("down")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(docker_environment)
    stop = next(call for call in calls if "stop" in call)
    assert "func" in stop and "orch" in stop and "ollama" in stop
    assert "devcontainer" not in stop
    assert not any("down" in call or "--volumes" in call for call in calls)
    assert any("rm" in call for call in calls)


def test_missing_daemon_fails_without_cleanup(docker_environment: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_INFO_EXIT", "1")
    result = run_stack("up")
    assert result.returncode != 0
    assert "Docker" in result.stderr
    assert not any("up" in call or "down" in call for call in docker_calls(docker_environment))


def test_devcontainer_missing_host_path_fails_closed(docker_environment: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANOPEX_DEVCONTAINER", "1")
    result = run_stack("up")
    assert result.returncode != 0
    assert "DEV_WORKSPACE" in result.stderr


def test_rebuild_is_explicit(docker_environment: Path) -> None:
    result = run_stack("rebuild")
    assert result.returncode == 0, result.stderr
    calls = docker_calls(docker_environment)
    build = next(index for index, call in enumerate(calls) if "build" in call)
    start = next(index for index, call in enumerate(calls) if "up" in call)
    assert build < start
    assert "--force-recreate" in calls[start]


def test_reset_requires_explicit_data_confirmation(docker_environment: Path) -> None:
    result = run_stack("clean")
    assert result.returncode != 0
    assert "DEV_RESET_DATA=1" in result.stderr
    assert not any("--volumes" in call for call in docker_calls(docker_environment))


def test_storage_failure_never_tears_down_the_project(
    docker_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCKER_UP_EXIT", "17")
    result = run_stack("storage")
    assert result.returncode == 17
    calls = docker_calls(docker_environment)
    assert not any("down" in call for call in calls)
    stop = next(call for call in calls if "stop" in call)
    assert stop[-2:] == ["azurite", "init-storage"]

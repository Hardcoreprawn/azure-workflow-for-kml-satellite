from __future__ import annotations

import signal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


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

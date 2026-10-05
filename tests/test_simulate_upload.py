from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from scripts import load_baseline, local_durable, simulate_upload


@pytest.mark.parametrize("poller", ["simulate", "load"])
def test_storage_native_polling_uses_local_management_without_customer_bearer(monkeypatch, poller):
    module = simulate_upload if poller == "simulate" else load_baseline
    requests = []
    monkeypatch.delenv("CANOPEX_API_BEARER_TOKEN", raising=False)

    def get(url, **kwargs):
        requests.append((url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"runtimeStatus": "Completed"})

    monkeypatch.setattr(local_durable.httpx, "get", get)
    if poller == "simulate":
        module.poll_orchestrator("run", timeout=2, interval=0)
    else:
        assert module._poll_status("run", timeout_s=2, poll_interval_s=0)[0] == "Completed"
    assert requests[0][0] == f"{module.FUNC_BASE}/runtime/webhooks/durabletask/instances/run"
    assert "Authorization" not in requests[0][1].get("headers", {})


class _DummyResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def test_fire_event_grid_includes_function_name_and_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _DummyResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _DummyResponse(202, "accepted")

    monkeypatch.setattr(simulate_upload.httpx, "post", _fake_post)
    monkeypatch.setattr(uuid, "uuid4", lambda: "test-id")

    instance_id = simulate_upload.fire_event_grid(
        blob_url="http://127.0.0.1:10000/devstoreaccount1/kml-input/file.kml",
        blob_name="file.kml",
        content_length=123,
        container="kml-input",
        function_name="blob_trigger",
        function_key="abc123",
    )

    assert instance_id == "test-id"
    assert captured["url"] == "http://localhost:7071/runtime/webhooks/eventgrid"
    assert captured["params"] == {"functionName": "blob_trigger", "code": "abc123"}


def test_fire_event_grid_redacts_key_in_logs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fake_post(*_: object, **__: object) -> _DummyResponse:
        return _DummyResponse(202, "accepted")

    monkeypatch.setattr(simulate_upload.httpx, "post", _fake_post)

    simulate_upload.fire_event_grid(
        blob_url="http://127.0.0.1:10000/devstoreaccount1/kml-input/file.kml",
        blob_name="file.kml",
        content_length=123,
        container="kml-input",
        function_name="blob_trigger",
        function_key="secret-key",
    )

    output = capsys.readouterr().out
    assert "secret-key" not in output
    assert "***REDACTED***" in output


def test_fire_event_grid_raises_on_rejected_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(*_: object, **__: object) -> _DummyResponse:
        return _DummyResponse(401, "Unauthorized")

    monkeypatch.setattr(simulate_upload.httpx, "post", _fake_post)

    with pytest.raises(RuntimeError, match="HTTP 401"):
        simulate_upload.fire_event_grid(
            blob_url="http://127.0.0.1:10000/devstoreaccount1/kml-input/file.kml",
            blob_name="file.kml",
            content_length=123,
            container="kml-input",
        )


def test_fire_event_grid_honours_func_base_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller running against a sibling container (e.g. the dev Event Grid
    relay service, #1269 follow-up) needs to target the func service by
    container name, not the localhost default."""
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _DummyResponse:
        captured["url"] = url
        return _DummyResponse(202, "accepted")

    monkeypatch.setattr(simulate_upload.httpx, "post", _fake_post)

    simulate_upload.fire_event_grid(
        blob_url="http://azurite:10000/devstoreaccount1/kml-input/file.kml",
        blob_name="file.kml",
        content_length=123,
        container="kml-input",
        func_base="http://func:80",
    )

    assert captured["url"] == "http://func:80/runtime/webhooks/eventgrid"

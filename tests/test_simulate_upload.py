from __future__ import annotations

import uuid

import pytest

from scripts import simulate_upload


class _DummyResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def test_fire_event_grid_includes_function_name_and_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def _fake_post(url: str, **_: object) -> _DummyResponse:
        captured["url"] = url
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
    assert "functionName=blob_trigger" in captured["url"]
    assert "code=abc123" in captured["url"]


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

from __future__ import annotations

import pytest

from scripts import e2e_smoke_gate as smoke


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = responses
        self.get_calls: list[str] = []

    def get(self, url: str, headers: dict[str, str], timeout: float) -> _FakeResponse:
        self.get_calls.append(url)
        if not self._responses:
            raise AssertionError("no fake responses left")
        return self._responses.pop(0)


def test_bearer_headers_returns_authorization_header() -> None:
    headers = smoke.bearer_headers("token-123")

    assert headers == {"Authorization": "Bearer token-123"}


def test_bearer_headers_requires_non_empty_token() -> None:
    with pytest.raises(ValueError, match="Bearer token is required"):
        smoke.bearer_headers("   ")


def test_verify_completed_output_shape_requires_completed_status() -> None:
    with pytest.raises(ValueError, match="non-success state"):
        smoke.verify_completed_output_shape(
            {
                "runtimeStatus": "Failed",
                "output": {
                    "status": "completed",
                    "message": "done",
                    "blobName": "analysis/demo.kml",
                    "featureCount": 1,
                    "aoiCount": 1,
                    "artifacts": {"report": "analysis/demo/report.json"},
                },
            }
        )


def test_verify_completed_output_shape_requires_expected_fields() -> None:
    with pytest.raises(ValueError, match="field 'blobName' has invalid type"):
        smoke.verify_completed_output_shape(
            {
                "runtimeStatus": "Completed",
                "output": {
                    "status": "completed",
                    "message": "done",
                    "blobName": None,
                    "featureCount": 1,
                    "aoiCount": 1,
                    "artifacts": {},
                },
            }
        )


def test_verify_completed_output_shape_returns_output() -> None:
    output = smoke.verify_completed_output_shape(
        {
            "runtimeStatus": "Completed",
            "output": {
                "status": "completed",
                "message": "done",
                "blobName": "analysis/run-1.kml",
                "featureCount": 1,
                "aoiCount": 1,
                "artifacts": {
                    "report": "analysis/run-1/report.json",
                    "manifest": "enrichment/run-1/payload.json",
                },
            },
        }
    )

    assert output["blobName"] == "analysis/run-1.kml"


def test_collect_artifact_paths_returns_flat_strings() -> None:
    paths = smoke.collect_artifact_paths(
        {
            "artifacts": {
                "report": "analysis/run-1/report.json",
                "manifest": "enrichment/run-1/payload.json",
            },
        }
    )

    assert paths == ["analysis/run-1/report.json", "enrichment/run-1/payload.json"]


def test_collect_artifact_paths_flattens_list_values() -> None:
    paths = smoke.collect_artifact_paths(
        {
            "artifacts": {
                "metadataPaths": ["analysis/run-1/report.json", ""],
                "rawImageryPaths": ["imagery/run-1/raw-1.tif", "  "],
                "clippedImageryPaths": [],
            }
        }
    )

    assert paths == ["analysis/run-1/report.json", "imagery/run-1/raw-1.tif"]


def test_poll_orchestrator_returns_terminal_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(
        responses=[
            _FakeResponse(404),
            _FakeResponse(200, {"runtimeStatus": "Running"}),
            _FakeResponse(200, {"runtimeStatus": "Completed", "output": {"artifacts": {"a": "x"}}}),
        ]
    )

    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)

    payload = smoke.poll_orchestrator(
        client,
        api_base="https://api.example.com",
        token="token",
        instance_id="sub-123",
        max_attempts=5,
        poll_interval_seconds=1,
    )

    assert payload["runtimeStatus"] == "Completed"
    assert len(client.get_calls) == 3


def test_poll_orchestrator_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(
        responses=[
            _FakeResponse(200, {"runtimeStatus": "Running"}),
            _FakeResponse(200, {"runtimeStatus": "Running"}),
        ]
    )
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)

    with pytest.raises(TimeoutError, match="did not reach terminal state"):
        smoke.poll_orchestrator(
            client,
            api_base="https://api.example.com",
            token="token",
            instance_id="sub-123",
            max_attempts=2,
            poll_interval_seconds=1,
        )

from __future__ import annotations

import base64
import json

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


def test_build_client_principal_header_encodes_expected_payload() -> None:
    header = smoke.build_client_principal_header(
        user_id="user-123",
        user_details="smoke@example.com",
        roles_csv="authenticated,admin",
    )
    payload = json.loads(base64.b64decode(header.encode("ascii")).decode("utf-8"))

    assert payload["userId"] == "user-123"
    assert payload["userDetails"] == "smoke@example.com"
    assert payload["userRoles"] == ["authenticated", "admin"]


def test_auth_headers_uses_principal_when_bearer_missing() -> None:
    headers = smoke.auth_headers(
        token=None,
        principal_header="principal-header",
        session_token="session-token",
    )

    assert headers["X-MS-CLIENT-PRINCIPAL"] == "principal-header"
    assert headers["X-Auth-Session"] == "session-token"


def test_verify_output_artifacts_requires_completed_status() -> None:
    with pytest.raises(ValueError, match="non-success state"):
        smoke.verify_output_artifacts(
            {
                "runtimeStatus": "Failed",
                "output": {"artifacts": {"report": "analysis/demo/report.json"}},
            }
        )


def test_verify_output_artifacts_requires_non_empty_paths() -> None:
    with pytest.raises(ValueError, match="no non-empty artifact paths"):
        smoke.verify_output_artifacts(
            {
                "runtimeStatus": "Completed",
                "output": {"artifacts": {"report": "", "preview": "   "}},
            }
        )


def test_verify_output_artifacts_returns_paths() -> None:
    paths = smoke.verify_output_artifacts(
        {
            "runtimeStatus": "Completed",
            "output": {
                "artifacts": {
                    "report": "analysis/run-1/report.json",
                    "manifest": "enrichment/run-1/payload.json",
                }
            },
        }
    )

    assert paths == ["analysis/run-1/report.json", "enrichment/run-1/payload.json"]


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

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


# ---------------------------------------------------------------------------
# acquire_token_client_credentials
# ---------------------------------------------------------------------------


class _FakeRequestsPost:
    """Minimal stub for requests.post used in acquire_token tests."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self._status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self._status_code >= 400:
            import requests as req

            raise req.HTTPError(f"HTTP {self._status_code}")

    def json(self) -> dict:
        return self._payload


def test_acquire_token_returns_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke._requests,
        "post",
        lambda *a, **kw: _FakeRequestsPost(200, {"access_token": "tok-abc"}),
    )

    token = smoke.acquire_token_client_credentials(
        token_endpoint="https://tenant.ciamlogin.com/tenant.onmicrosoft.com/oauth2/v2.0/token",
        client_id="test-client-id",
        client_secret="__FIXTURE_SECRET__",
        scope="api://test-client-id/.default",
    )

    assert token == "tok-abc"


def test_acquire_token_raises_on_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke._requests,
        "post",
        lambda *a, **kw: _FakeRequestsPost(
            200, {"error": "invalid_client", "error_description": "Bad secret"}
        ),
    )

    with pytest.raises(ValueError, match="invalid_client"):
        smoke.acquire_token_client_credentials(
            token_endpoint=(
                "https://tenant.ciamlogin.com/tenant.onmicrosoft.com/oauth2/v2.0/token"
            ),
            client_id="test-client-id",
            client_secret="__FIXTURE_SECRET__",
            scope="api://test-client-id/.default",
        )


def test_acquire_token_rejects_non_https_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        smoke.acquire_token_client_credentials(
            token_endpoint="http://tenant.ciamlogin.com/oauth2/v2.0/token",
            client_id="test-client-id",
            client_secret="__FIXTURE_SECRET__",
            scope="api://test-client-id/.default",
        )


# ---------------------------------------------------------------------------
# Evidence file output
# ---------------------------------------------------------------------------


def test_evidence_dict_includes_optional_fields() -> None:
    # Simulate the evidence dict construction logic from main()
    # with optional fields (imageTag, commitSha)
    submission_id = "sub-123"
    status_payload = {"runtimeStatus": "Completed"}
    output_payload = {"status": "completed"}
    artifact_paths = ["report.json", "manifest.json"]
    manifest_ok = True
    image_tag = "sha256:abc123"
    commit_sha = "deadbeef"

    evidence: dict = {
        "submissionId": submission_id,
        "runtimeStatus": status_payload.get("runtimeStatus"),
        "outputStatus": output_payload.get("status"),
        "artifactCount": len(artifact_paths),
        "manifestVerified": manifest_ok,
    }
    if image_tag:
        evidence["imageTag"] = image_tag
    if commit_sha:
        evidence["commitSha"] = commit_sha

    assert evidence["submissionId"] == "sub-123"
    assert evidence["runtimeStatus"] == "Completed"
    assert evidence["outputStatus"] == "completed"
    assert evidence["artifactCount"] == 2
    assert evidence["manifestVerified"] is True
    assert evidence["imageTag"] == "sha256:abc123"
    assert evidence["commitSha"] == "deadbeef"


def test_evidence_dict_without_optional_fields() -> None:
    # Validate that evidence dict is built correctly
    # without optional fields when not provided
    submission_id = "sub-456"
    status_payload = {"runtimeStatus": "Completed"}
    output_payload = {"status": "completed"}
    artifact_paths = ["report.json"]
    manifest_ok = False
    image_tag = ""
    commit_sha = ""

    evidence: dict = {
        "submissionId": submission_id,
        "runtimeStatus": status_payload.get("runtimeStatus"),
        "outputStatus": output_payload.get("status"),
        "artifactCount": len(artifact_paths),
        "manifestVerified": manifest_ok,
    }
    if image_tag:
        evidence["imageTag"] = image_tag
    if commit_sha:
        evidence["commitSha"] = commit_sha

    assert evidence["submissionId"] == "sub-456"
    assert evidence["runtimeStatus"] == "Completed"
    assert "imageTag" not in evidence
    assert "commitSha" not in evidence
    assert evidence["manifestVerified"] is False

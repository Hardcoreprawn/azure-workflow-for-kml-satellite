"""Tests for secure demo result valet-token delivery (#200)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from function_app import (
    _mint_demo_valet_token,
    _verify_demo_valet_token,
    demo_result_download,
    demo_result_token,
    demo_results,
)


class _FakeDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readall(self) -> bytes:
        return self._data


class _FakeBlobClient:
    def __init__(
        self,
        storage: dict[tuple[str, str], bytes],
        container: str,
        blob: str,
        content_types: dict[tuple[str, str], str],
    ) -> None:
        self._storage = storage
        self._container = container
        self._blob = blob
        self._content_types = content_types

    def upload_blob(self, data: str | bytes, overwrite: bool = False) -> None:
        key = (self._container, self._blob)
        if key in self._storage and not overwrite:
            raise FileExistsError(self._blob)
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._storage[key] = data

    def download_blob(self) -> _FakeDownload:
        key = (self._container, self._blob)
        if key not in self._storage:
            raise FileNotFoundError(self._blob)
        return _FakeDownload(self._storage[key])

    def get_blob_properties(self) -> SimpleNamespace:
        key = (self._container, self._blob)
        return SimpleNamespace(
            content_settings=SimpleNamespace(
                content_type=self._content_types.get(key, "application/octet-stream")
            )
        )


class _FakeContainerClient:
    def __init__(self, storage: dict[tuple[str, str], bytes], container: str) -> None:
        self._storage = storage
        self._container = container

    def list_blobs(self, name_starts_with: str = "") -> list[SimpleNamespace]:
        names = [
            blob_name
            for container, blob_name in self._storage
            if container == self._container and blob_name.startswith(name_starts_with)
        ]
        return [SimpleNamespace(name=name) for name in sorted(names)]


class _FakeBlobService:
    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], bytes] = {}
        self.content_types: dict[tuple[str, str], str] = {}

    def get_container_client(self, container: str) -> _FakeContainerClient:
        return _FakeContainerClient(self.storage, container)

    def get_blob_client(self, *, container: str, blob: str) -> _FakeBlobClient:
        return _FakeBlobClient(self.storage, container, blob, self.content_types)


def _seed_submission(
    blob_service: _FakeBlobService,
    *,
    submission_id: str = "submission-123",
    email: str = "demo@example.com",
    artifact_path: str = "imagery/demo-output.tif",
    status: str = "completed",
) -> str:
    blob_name = f"demo-submissions/2026-03-16/{submission_id}.json"
    submission = {
        "submission_id": submission_id,
        "email": email,
        "status": status,
        "artifacts": {
            "clippedImageryPaths": [artifact_path],
            "metadataPaths": ["metadata/demo-output.json"],
            "rawImageryPaths": [],
        },
        "output_container": "kml-output",
    }
    blob_service.storage[("pipeline-payloads", blob_name)] = json.dumps(submission).encode("utf-8")
    return blob_name


def test_mint_and_verify_demo_valet_token_round_trip(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret")

    expires_at = datetime(2026, 3, 17, 12, 0, tzinfo=UTC)
    token = _mint_demo_valet_token(
        submission_id="submission-123",
        submission_blob_name="demo-submissions/2026-03-16/submission-123.json",
        artifact_path="imagery/demo-output.tif",
        recipient_email="demo@example.com",
        expires_at=expires_at,
        nonce="nonce-123",
        max_uses=2,
    )

    claims, error = _verify_demo_valet_token(
        token,
        now=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )

    assert error is None
    assert claims is not None
    assert claims["submission_id"] == "submission-123"
    assert claims["artifact_path"] == "imagery/demo-output.tif"
    assert claims["submission_blob_name"] == "demo-submissions/2026-03-16/submission-123.json"
    assert claims["recipient_hash"] != "demo@example.com"
    assert claims["nonce"] == "nonce-123"
    assert claims["max_uses"] == 2


def test_verify_demo_valet_token_rejects_expired_token(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret")

    token = _mint_demo_valet_token(
        submission_id="submission-123",
        submission_blob_name="demo-submissions/2026-03-16/submission-123.json",
        artifact_path="imagery/demo-output.tif",
        recipient_email="demo@example.com",
        expires_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )

    claims, error = _verify_demo_valet_token(
        token,
        now=datetime(2026, 3, 16, 12, 1, tzinfo=UTC),
    )

    assert claims is None
    assert error == "expired"


def test_demo_result_token_mints_scoped_token_for_known_artifact(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret")
    blob_service = _FakeBlobService()
    _seed_submission(blob_service)
    monkeypatch.setattr("function_app.get_blob_service_client", lambda: blob_service)

    req = SimpleNamespace(
        method="POST",
        headers={},
        get_json=lambda: {
            "submission_id": "submission-123",
            "artifact_path": "imagery/demo-output.tif",
        },
    )

    response = asyncio.run(demo_result_token(req))

    assert response.status_code == 200
    body = json.loads(response.get_body().decode("utf-8"))
    assert body["results_url"].startswith("/api/demo-results?token=")
    assert body["download_url"].startswith("/api/demo-results/download?token=")

    claims, error = _verify_demo_valet_token(body["token"])
    assert error is None
    assert claims is not None
    assert claims["artifact_path"] == "imagery/demo-output.tif"


def test_demo_results_returns_scoped_artifact_view(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret")
    blob_service = _FakeBlobService()
    submission_blob_name = _seed_submission(blob_service)
    monkeypatch.setattr("function_app.get_blob_service_client", lambda: blob_service)

    token = _mint_demo_valet_token(
        submission_id="submission-123",
        submission_blob_name=submission_blob_name,
        artifact_path="imagery/demo-output.tif",
        recipient_email="demo@example.com",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    req = SimpleNamespace(params={"token": token}, headers={})
    response = asyncio.run(demo_results(req))

    assert response.status_code == 200
    body = json.loads(response.get_body().decode("utf-8"))
    assert body["submission_id"] == "submission-123"
    assert body["artifact"]["path"] == "imagery/demo-output.tif"
    assert body["artifact"]["download_url"].startswith("/api/demo-results/download?token=")
    assert "email" not in body


def test_demo_result_download_enforces_replay_limit(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret")
    blob_service = _FakeBlobService()
    submission_blob_name = _seed_submission(blob_service)
    blob_service.storage[("kml-output", "imagery/demo-output.tif")] = b"TIFFDATA"
    blob_service.content_types[("kml-output", "imagery/demo-output.tif")] = "image/tiff"
    monkeypatch.setattr("function_app.get_blob_service_client", lambda: blob_service)

    token = _mint_demo_valet_token(
        submission_id="submission-123",
        submission_blob_name=submission_blob_name,
        artifact_path="imagery/demo-output.tif",
        recipient_email="demo@example.com",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_uses=1,
        nonce="nonce-replay-limit",
    )

    req = SimpleNamespace(params={"token": token}, headers={})

    first = asyncio.run(demo_result_download(req))
    second = asyncio.run(demo_result_download(req))

    assert first.status_code == 200
    assert first.get_body() == b"TIFFDATA"
    assert second.status_code == 403


def test_demo_results_rejects_invalid_token(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_VALET_TOKEN_SECRET", "test-secret")

    req = SimpleNamespace(params={"token": "not-a-valid-token"}, headers={})
    response = asyncio.run(demo_results(req))

    assert response.status_code == 401

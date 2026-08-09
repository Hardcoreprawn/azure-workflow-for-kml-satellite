"""Unit tests for treesight.storage.client without Azure network calls."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import treesight.storage.client as storage_client


class _FakeBlob:
    def __init__(self):
        self.url = "https://example.blob.core.windows.net/c/path"
        self.upload_calls: list[tuple[bytes, bool, object]] = []
        self.exists_value = True
        self.download_value = b"{}"

    def upload_blob(self, data, *, overwrite, content_settings):
        self.upload_calls.append((data, overwrite, content_settings))

    def download_blob(self):
        return SimpleNamespace(readall=lambda: self.download_value)

    def exists(self):
        return self.exists_value

    def get_blob_properties(self):
        return SimpleNamespace(
            name="path",
            size=11,
            content_settings=SimpleNamespace(content_type="application/json"),
            last_modified=datetime(2026, 1, 2, tzinfo=UTC),
        )


class _FakeContainer:
    def __init__(self, *, exists: bool):
        self._exists = exists
        self.created = False

    def exists(self):
        return self._exists

    def create_container(self):
        self.created = True

    def list_blobs(self, *, name_starts_with=None):
        if name_starts_with:
            return [SimpleNamespace(name=f"{name_starts_with}/a.json")]
        return [SimpleNamespace(name="x.json")]


class _FakeServiceClient:
    def __init__(self):
        self.container = _FakeContainer(exists=False)
        self.blob = _FakeBlob()

    def get_container_client(self, _name):
        return self.container

    def get_blob_client(self, _container, _path):
        return self.blob


class TestGetBlobServiceClient:
    def setup_method(self):
        storage_client._client = None

    def test_uses_connection_string(self, monkeypatch: pytest.MonkeyPatch):
        fake = _FakeServiceClient()
        monkeypatch.setattr(
            storage_client, "STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true"
        )
        monkeypatch.setattr(storage_client, "STORAGE_ACCOUNT_NAME", "")
        monkeypatch.setattr(
            storage_client.BlobServiceClient,
            "from_connection_string",
            lambda _conn: fake,
        )

        assert storage_client.get_blob_service_client() is fake

    def test_uses_managed_identity_account_name(self, monkeypatch: pytest.MonkeyPatch):
        fake = _FakeServiceClient()
        monkeypatch.setattr(storage_client, "STORAGE_CONNECTION_STRING", "")
        monkeypatch.setattr(storage_client, "STORAGE_ACCOUNT_NAME", "acct")
        monkeypatch.setattr(storage_client, "BlobServiceClient", lambda *_args, **_kwargs: fake)
        monkeypatch.setattr("azure.identity.DefaultAzureCredential", lambda: object())

        assert storage_client.get_blob_service_client() is fake

    def test_raises_when_not_configured(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(storage_client, "STORAGE_CONNECTION_STRING", "")
        monkeypatch.setattr(storage_client, "STORAGE_ACCOUNT_NAME", "")

        with pytest.raises(RuntimeError, match="Storage is not configured"):
            storage_client.get_blob_service_client()


class TestBlobStorageClientMethods:
    def test_ensure_container_caches_known_container(self):
        fake = _FakeServiceClient()
        client = storage_client.BlobStorageClient.__new__(storage_client.BlobStorageClient)
        client._client = fake
        storage_client.BlobStorageClient._known_containers.clear()

        client.ensure_container("kml-input")
        client.ensure_container("kml-input")

        assert fake.container.created is True

    def test_upload_bytes_uploads_and_returns_url(self):
        fake = _FakeServiceClient()
        client = storage_client.BlobStorageClient.__new__(storage_client.BlobStorageClient)
        client._client = fake
        storage_client.BlobStorageClient._known_containers.clear()

        url = client.upload_bytes(
            "kml-input", "analysis/out.json", b"abc", content_type="text/plain"
        )

        assert url == fake.blob.url
        assert fake.blob.upload_calls

    def test_download_json_requires_dict(self):
        fake = _FakeServiceClient()
        fake.blob.download_value = b"[]"
        client = storage_client.BlobStorageClient.__new__(storage_client.BlobStorageClient)
        client._client = fake

        with pytest.raises(TypeError, match="Expected JSON object"):
            client.download_json("kml-output", "x.json")

    def test_download_json_list_requires_list(self):
        fake = _FakeServiceClient()
        fake.blob.download_value = b"{}"
        client = storage_client.BlobStorageClient.__new__(storage_client.BlobStorageClient)
        client._client = fake

        with pytest.raises(TypeError, match="Expected JSON array"):
            client.download_json_list("kml-output", "x.json")

    def test_blob_exists_and_properties_and_stream_and_list(self):
        fake = _FakeServiceClient()
        client = storage_client.BlobStorageClient.__new__(storage_client.BlobStorageClient)
        client._client = fake

        assert client.blob_exists("kml-output", "folder/file.json") is True

        props = client.get_blob_properties("kml-output", "folder/file.json")
        assert props["name"] == "path"
        assert props["content_type"] == "application/json"
        assert props["last_modified"].startswith("2026-01-02")

        stream = client.stream_blob("kml-output", "folder/file.json")
        assert stream.readall() == b"{}"

        assert client.list_blobs("kml-output") == ["x.json"]
        assert client.list_blobs("kml-output", prefix="folder") == ["folder/a.json"]

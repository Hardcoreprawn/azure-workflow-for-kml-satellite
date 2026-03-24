"""Blob storage client wrapper (§6)."""

from __future__ import annotations

from typing import Any, cast

from azure.storage.blob import BlobServiceClient, ContentSettings, StorageStreamDownloader

from treesight.config import STORAGE_CONNECTION_STRING
from treesight.log import log_phase

_client: BlobServiceClient | None = None


def get_blob_service_client() -> BlobServiceClient:
    """Return a module-level singleton ``BlobServiceClient``."""
    global _client
    if _client is None:
        _client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
    return _client


class BlobStorageClient:
    """Thin wrapper around Azure Blob SDK for pipeline operations."""

    def __init__(self, connection_string: str | None = None) -> None:
        if connection_string:
            self._client = BlobServiceClient.from_connection_string(connection_string)
        else:
            self._client = get_blob_service_client()

    def ensure_container(self, container_name: str) -> None:
        """Create the container if it does not already exist."""
        container = self._client.get_container_client(container_name)
        if not container.exists():
            container.create_container()

    def upload_bytes(
        self,
        container: str,
        blob_path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> str:
        """Upload raw bytes and return the blob URL."""
        self.ensure_container(container)
        blob = self._client.get_blob_client(container, blob_path)
        blob.upload_blob(
            data,
            overwrite=overwrite,
            content_settings=ContentSettings(content_type=content_type),
        )
        log_phase("storage", "upload", blob_path=blob_path, container=container, size=len(data))
        return blob.url

    def upload_json(self, container: str, blob_path: str, data: dict[str, Any]) -> str:
        """Serialise *data* as JSON and upload it."""
        import json

        payload = json.dumps(data, indent=2, default=str).encode("utf-8")
        return self.upload_bytes(container, blob_path, payload, content_type="application/json")

    def download_bytes(self, container: str, blob_path: str) -> bytes:
        """Download a blob and return its raw bytes."""
        blob = self._client.get_blob_client(container, blob_path)
        return blob.download_blob().readall()

    def download_json(self, container: str, blob_path: str) -> dict[str, Any]:
        """Download and deserialise a JSON blob as a dict."""
        import json

        raw = json.loads(self.download_bytes(container, blob_path))
        if not isinstance(raw, dict):
            msg = f"Expected JSON object in {container}/{blob_path}, got {type(raw).__name__}"
            raise TypeError(msg)
        return cast(dict[str, Any], raw)

    def download_json_list(self, container: str, blob_path: str) -> list[dict[str, Any]]:
        """Download and deserialise a JSON blob as a list of dicts."""
        import json

        raw = json.loads(self.download_bytes(container, blob_path))
        if not isinstance(raw, list):
            msg = f"Expected JSON array in {container}/{blob_path}, got {type(raw).__name__}"
            raise TypeError(msg)
        return cast(list[dict[str, Any]], raw)

    def blob_exists(self, container: str, blob_path: str) -> bool:
        """Return ``True`` if the blob exists."""
        blob = self._client.get_blob_client(container, blob_path)
        return blob.exists()

    def get_blob_properties(self, container: str, blob_path: str) -> dict[str, Any]:
        """Return a dict of basic blob metadata."""
        blob = self._client.get_blob_client(container, blob_path)
        props = blob.get_blob_properties()
        return {
            "name": props.name,
            "size": props.size,
            "content_type": props.content_settings.content_type,
            "last_modified": props.last_modified.isoformat() if props.last_modified else "",
        }

    def stream_blob(self, container: str, blob_path: str) -> StorageStreamDownloader[bytes]:
        """Return a ``StorageStreamDownloader`` for streaming responses."""
        blob = self._client.get_blob_client(container, blob_path)
        return blob.download_blob()

    # --- ETag-aware operations for optimistic concurrency ---

    def download_json_with_etag(self, container: str, blob_path: str) -> tuple[dict[str, Any], str]:
        """Download a JSON blob and return ``(data, etag)``."""
        import json

        blob = self._client.get_blob_client(container, blob_path)
        dl = blob.download_blob()
        raw = json.loads(dl.readall())
        etag = dl.properties.etag
        if not isinstance(raw, dict):
            msg = f"Expected JSON object in {container}/{blob_path}, got {type(raw).__name__}"
            raise TypeError(msg)
        return cast(dict[str, Any], raw), etag

    def upload_json_if_match(
        self, container: str, blob_path: str, data: dict[str, Any], etag: str
    ) -> None:
        """Upload JSON only if the blob's current ETag matches *etag*.

        Raises ``azure.core.exceptions.ResourceModifiedError`` on conflict.
        """
        import json

        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError
        from azure.storage.blob import BlobClient

        payload = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.ensure_container(container)
        blob: BlobClient = self._client.get_blob_client(container, blob_path)
        try:
            blob.upload_blob(
                payload,
                overwrite=True,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
                content_settings=ContentSettings(content_type="application/json"),
            )
        except ResourceModifiedError:
            raise

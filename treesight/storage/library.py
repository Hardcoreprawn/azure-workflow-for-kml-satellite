"""User library — blob-backed KML and analysis persistence (M4.4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from treesight.constants import PIPELINE_PAYLOADS_CONTAINER
from treesight.storage.client import BlobStorageClient

# Maximum items per user to prevent unbounded growth
MAX_KMLS_PER_USER = 100
MAX_ANALYSES_PER_USER = 200


def _library_path(user_id: str) -> str:
    return f"users/{user_id}/library.json"


def _kml_blob_path(user_id: str, kml_id: str) -> str:
    return f"users/{user_id}/kmls/{kml_id}.kml"


def _empty_library() -> dict[str, Any]:
    return {"kmls": [], "analyses": []}


class UserLibrary:
    """Per-user KML and analysis library backed by blob storage."""

    def __init__(self, user_id: str, storage: BlobStorageClient | None = None) -> None:
        if not user_id or user_id == "anonymous":
            msg = "Authenticated user required for library operations"
            raise ValueError(msg)
        self._user_id = user_id
        self._storage = storage or BlobStorageClient()
        self._container = PIPELINE_PAYLOADS_CONTAINER

    def get_library(self) -> dict[str, Any]:
        """Return the full library manifest, or an empty one if absent."""
        path = _library_path(self._user_id)
        if not self._storage.blob_exists(self._container, path):
            return _empty_library()
        return self._storage.download_json(self._container, path)

    def _save_library(self, library: dict[str, Any]) -> None:
        self._storage.upload_json(self._container, _library_path(self._user_id), library)

    # --- KML operations ---

    def add_kml(
        self,
        name: str,
        kml_bytes: bytes,
        *,
        polygon_count: int = 0,
        bbox: list[float] | None = None,
    ) -> dict[str, Any]:
        """Store a KML file and add it to the library index. Returns the record."""
        library = self.get_library()
        if len(library["kmls"]) >= MAX_KMLS_PER_USER:
            msg = f"KML limit ({MAX_KMLS_PER_USER}) reached"
            raise ValueError(msg)

        kml_id = str(uuid.uuid4())
        blob_path = _kml_blob_path(self._user_id, kml_id)

        self._storage.upload_bytes(
            self._container,
            blob_path,
            kml_bytes,
            content_type="application/vnd.google-earth.kml+xml",
        )

        record: dict[str, Any] = {
            "id": kml_id,
            "name": name,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "size_bytes": len(kml_bytes),
            "polygon_count": polygon_count,
        }
        if bbox:
            record["bbox"] = bbox

        library["kmls"].append(record)
        self._save_library(library)
        return record

    def get_kml(self, kml_id: str) -> bytes:
        """Download KML file bytes. Raises FileNotFoundError if absent."""
        blob_path = _kml_blob_path(self._user_id, kml_id)
        if not self._storage.blob_exists(self._container, blob_path):
            msg = f"KML {kml_id} not found"
            raise FileNotFoundError(msg)
        return self._storage.download_bytes(self._container, blob_path)

    def delete_kml(self, kml_id: str) -> bool:
        """Remove a KML from the library. Returns True if found."""
        library = self.get_library()
        original_len = len(library["kmls"])
        library["kmls"] = [k for k in library["kmls"] if k["id"] != kml_id]
        if len(library["kmls"]) == original_len:
            return False

        # Remove the blob
        blob_path = _kml_blob_path(self._user_id, kml_id)
        self._storage.delete_blob(self._container, blob_path)

        # Remove linked analyses
        library["analyses"] = [a for a in library["analyses"] if a.get("kml_id") != kml_id]

        self._save_library(library)
        return True

    # --- Analysis operations ---

    def add_analysis(
        self,
        *,
        kml_id: str,
        kml_name: str,
        instance_id: str,
        aoi_name: str = "",
        status: str = "running",
    ) -> dict[str, Any]:
        """Record a pipeline analysis run in the library. Returns the record."""
        library = self.get_library()
        if len(library["analyses"]) >= MAX_ANALYSES_PER_USER:
            msg = f"Analysis limit ({MAX_ANALYSES_PER_USER}) reached"
            raise ValueError(msg)

        analysis_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "id": analysis_id,
            "kml_id": kml_id,
            "kml_name": kml_name,
            "instance_id": instance_id,
            "aoi_name": aoi_name or kml_name,
            "created_at": datetime.now(UTC).isoformat(),
            "status": status,
        }

        library["analyses"].append(record)
        self._save_library(library)
        return record

    def update_analysis_status(self, analysis_id: str, status: str, **extra: Any) -> bool:
        """Update the status (and optional extra fields) of an analysis."""
        library = self.get_library()
        for analysis in library["analyses"]:
            if analysis["id"] == analysis_id:
                analysis["status"] = status
                analysis.update(extra)
                self._save_library(library)
                return True
        return False

    def update_analysis_extra(self, analysis_id: str, **extra: Any) -> bool:
        """Update extra fields on an analysis without changing status."""
        library = self.get_library()
        for analysis in library["analyses"]:
            if analysis["id"] == analysis_id:
                analysis.update(extra)
                self._save_library(library)
                return True
        return False

    def delete_analysis(self, analysis_id: str) -> bool:
        """Remove an analysis from the library. Returns True if found."""
        library = self.get_library()
        original_len = len(library["analyses"])
        library["analyses"] = [a for a in library["analyses"] if a["id"] != analysis_id]
        if len(library["analyses"]) == original_len:
            return False
        self._save_library(library)
        return True

    # --- GDPR data rights ---

    def export_all_data(self) -> dict[str, Any]:
        """Export all user data as a structured dict (Article 20 portability).

        Returns a JSON-serialisable dict containing the library manifest,
        all KML file contents (base64-encoded), and quota record.
        """
        import base64

        library = self.get_library()

        # Attach KML file contents
        kmls_with_content: list[dict[str, Any]] = []
        for kml in library.get("kmls", []):
            entry = dict(kml)
            try:
                raw = self.get_kml(kml["id"])
                entry["content_base64"] = base64.b64encode(raw).decode("ascii")
            except FileNotFoundError:
                entry["content_base64"] = None
            kmls_with_content.append(entry)

        # Quota record
        quota_path = f"quotas/{self._user_id}.json"
        try:
            quota = self._storage.download_json(self._container, quota_path)
        except Exception:
            quota = None

        return {
            "user_id": self._user_id,
            "exported_at": datetime.now(UTC).isoformat(),
            "library": {
                "kmls": kmls_with_content,
                "analyses": library.get("analyses", []),
            },
            "quota": quota,
        }

    def delete_all_data(self) -> dict[str, int | str]:
        """Erase all user data (Article 17 right to erasure).

        Deletes every blob under the user prefix, the quota record,
        and returns a summary of what was removed.
        """
        deleted_count = 0

        # Delete all blobs under users/{user_id}/
        user_prefix = f"users/{self._user_id}/"
        blobs = self._storage.list_blobs(self._container, user_prefix)
        for blob_name in blobs:
            if self._storage.delete_blob(self._container, blob_name):
                deleted_count += 1

        # Delete quota record
        quota_path = f"quotas/{self._user_id}.json"
        if self._storage.delete_blob(self._container, quota_path):
            deleted_count += 1

        return {"blobs_deleted": deleted_count, "user_id": self._user_id}

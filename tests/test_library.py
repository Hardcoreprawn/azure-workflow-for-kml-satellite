"""Tests for the user library storage layer and GDPR data rights."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_storage(
    library: dict[str, Any] | None = None,
    *,
    blob_exists: bool = True,
) -> MagicMock:
    """Return a mock ``BlobStorageClient`` pre-loaded with *library*."""
    storage = MagicMock()
    storage.blob_exists.return_value = blob_exists
    if library is not None:
        storage.download_json.return_value = library
    else:
        storage.blob_exists.return_value = False
    storage.upload_bytes.return_value = "https://store.blob.core.windows.net/test/blob"
    storage.upload_json.return_value = "https://store.blob.core.windows.net/test/blob"
    storage.download_bytes.return_value = b"<kml>test</kml>"
    storage.delete_blob.return_value = True
    storage.list_blobs.return_value = []
    return storage


# ---------------------------------------------------------------------------
# UserLibrary — construction
# ---------------------------------------------------------------------------


class TestUserLibraryInit:
    def test_rejects_anonymous(self) -> None:
        import pytest

        from treesight.storage.library import UserLibrary

        with pytest.raises(ValueError, match="Authenticated user"):
            UserLibrary("anonymous")

    def test_rejects_empty_user_id(self) -> None:
        import pytest

        from treesight.storage.library import UserLibrary

        with pytest.raises(ValueError, match="Authenticated user"):
            UserLibrary("")

    def test_accepts_valid_user_id(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        lib = UserLibrary("user-123", storage=storage)
        assert lib._user_id == "user-123"


# ---------------------------------------------------------------------------
# UserLibrary — get_library
# ---------------------------------------------------------------------------


class TestGetLibrary:
    def test_returns_empty_when_no_manifest(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()  # blob_exists=False by default
        lib = UserLibrary("user-123", storage=storage)
        result = lib.get_library()
        assert result == {"kmls": [], "analyses": []}

    def test_returns_stored_library(self) -> None:
        from treesight.storage.library import UserLibrary

        data = {"kmls": [{"id": "k1"}], "analyses": []}
        storage = _mock_storage(data)
        lib = UserLibrary("user-123", storage=storage)
        result = lib.get_library()
        assert len(result["kmls"]) == 1


# ---------------------------------------------------------------------------
# UserLibrary — KML CRUD
# ---------------------------------------------------------------------------


class TestKmlOperations:
    def test_add_kml_stores_blob_and_updates_manifest(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        lib = UserLibrary("user-123", storage=storage)
        record = lib.add_kml("Test KML", b"<kml>data</kml>", polygon_count=2)

        assert record["name"] == "Test KML"
        assert record["size_bytes"] == len(b"<kml>data</kml>")
        assert record["polygon_count"] == 2
        assert "id" in record
        assert "uploaded_at" in record

        # Verify storage calls
        storage.upload_bytes.assert_called_once()
        storage.upload_json.assert_called_once()

    def test_add_kml_enforces_limit(self) -> None:
        import pytest

        from treesight.storage.library import MAX_KMLS_PER_USER, UserLibrary

        full_lib = {"kmls": [{"id": f"k{i}"} for i in range(MAX_KMLS_PER_USER)], "analyses": []}
        storage = _mock_storage(full_lib)
        lib = UserLibrary("user-123", storage=storage)

        with pytest.raises(ValueError, match="KML limit"):
            lib.add_kml("One Too Many", b"<kml/>")

    def test_get_kml_returns_bytes(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        storage.blob_exists.return_value = True
        storage.download_bytes.return_value = b"<kml>content</kml>"

        lib = UserLibrary("user-123", storage=storage)
        result = lib.get_kml("kml-id-1")
        assert result == b"<kml>content</kml>"

    def test_get_kml_raises_when_missing(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        storage.blob_exists.return_value = False

        lib = UserLibrary("user-123", storage=storage)

        import pytest

        with pytest.raises(FileNotFoundError):
            lib.get_kml("nonexistent")

    def test_delete_kml_removes_blob_and_linked_analyses(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {
            "kmls": [{"id": "k1"}, {"id": "k2"}],
            "analyses": [
                {"id": "a1", "kml_id": "k1"},
                {"id": "a2", "kml_id": "k2"},
            ],
        }
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.delete_kml("k1") is True

        # Check the library was saved with k1 and its analysis removed
        saved = storage.upload_json.call_args[0][2]
        assert len(saved["kmls"]) == 1
        assert saved["kmls"][0]["id"] == "k2"
        assert len(saved["analyses"]) == 1
        assert saved["analyses"][0]["kml_id"] == "k2"

        storage.delete_blob.assert_called_once()

    def test_delete_kml_returns_false_when_not_found(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {"kmls": [{"id": "k1"}], "analyses": []}
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.delete_kml("nonexistent") is False


# ---------------------------------------------------------------------------
# UserLibrary — Analysis CRUD
# ---------------------------------------------------------------------------


class TestAnalysisOperations:
    def test_add_analysis_creates_record(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        lib = UserLibrary("user-123", storage=storage)
        record = lib.add_analysis(
            kml_id="k1",
            kml_name="Test",
            instance_id="inst-1",
            aoi_name="AOI",
        )
        assert record["kml_id"] == "k1"
        assert record["instance_id"] == "inst-1"
        assert record["status"] == "running"
        assert "id" in record
        assert "created_at" in record

    def test_add_analysis_enforces_limit(self) -> None:
        import pytest

        from treesight.storage.library import MAX_ANALYSES_PER_USER, UserLibrary

        full_lib = {
            "kmls": [],
            "analyses": [{"id": f"a{i}"} for i in range(MAX_ANALYSES_PER_USER)],
        }
        storage = _mock_storage(full_lib)
        lib = UserLibrary("user-123", storage=storage)

        with pytest.raises(ValueError, match="Analysis limit"):
            lib.add_analysis(kml_id="k1", kml_name="X", instance_id="inst")

    def test_update_analysis_status(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {
            "kmls": [],
            "analyses": [{"id": "a1", "status": "running"}],
        }
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.update_analysis_status("a1", "completed", frame_count=30) is True

        saved = storage.upload_json.call_args[0][2]
        assert saved["analyses"][0]["status"] == "completed"
        assert saved["analyses"][0]["frame_count"] == 30

    def test_update_analysis_returns_false_when_missing(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {"kmls": [], "analyses": []}
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.update_analysis_status("nonexistent", "completed") is False

    def test_update_analysis_extra_without_status(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {
            "kmls": [],
            "analyses": [{"id": "a1", "status": "completed"}],
        }
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.update_analysis_extra("a1", summary='{"ndvi_delta":-0.08}') is True

        saved = storage.upload_json.call_args[0][2]
        assert saved["analyses"][0]["status"] == "completed"  # unchanged
        assert saved["analyses"][0]["summary"] == '{"ndvi_delta":-0.08}'

    def test_update_analysis_extra_returns_false_when_missing(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {"kmls": [], "analyses": []}
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.update_analysis_extra("nonexistent", summary="test") is False

    def test_delete_analysis(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {
            "kmls": [],
            "analyses": [{"id": "a1"}, {"id": "a2"}],
        }
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.delete_analysis("a1") is True

        saved = storage.upload_json.call_args[0][2]
        assert len(saved["analyses"]) == 1
        assert saved["analyses"][0]["id"] == "a2"

    def test_delete_analysis_returns_false_when_missing(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {"kmls": [], "analyses": []}
        storage = _mock_storage(lib_data)
        lib = UserLibrary("user-123", storage=storage)

        assert lib.delete_analysis("nonexistent") is False


# ---------------------------------------------------------------------------
# GDPR — export_all_data (Article 20)
# ---------------------------------------------------------------------------


class TestExportAllData:
    def test_export_includes_kmls_with_content(self) -> None:
        import base64

        from treesight.storage.library import UserLibrary

        lib_data = {
            "kmls": [{"id": "k1", "name": "Test"}],
            "analyses": [{"id": "a1", "kml_id": "k1"}],
        }
        storage = _mock_storage(lib_data)
        storage.download_bytes.return_value = b"<kml>my data</kml>"

        lib = UserLibrary("user-123", storage=storage)
        export = lib.export_all_data()

        assert export["user_id"] == "user-123"
        assert "exported_at" in export
        assert len(export["library"]["kmls"]) == 1
        assert export["library"]["kmls"][0]["content_base64"] == base64.b64encode(
            b"<kml>my data</kml>"
        ).decode("ascii")
        assert len(export["library"]["analyses"]) == 1

    def test_export_handles_missing_kml_file(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {"kmls": [{"id": "k1", "name": "Ghost"}], "analyses": []}
        storage = _mock_storage(lib_data)

        # Library manifest exists, but the individual KML blob is gone
        def exists_side_effect(container, path):
            return "library.json" in path

        storage.blob_exists.side_effect = exists_side_effect

        lib = UserLibrary("user-123", storage=storage)
        export = lib.export_all_data()

        assert export["library"]["kmls"][0]["content_base64"] is None

    def test_export_includes_quota(self) -> None:
        from treesight.storage.library import UserLibrary

        lib_data = {"kmls": [], "analyses": []}
        storage = _mock_storage(lib_data)

        # download_json called for library first, then quota
        quota_data = {"used": 3, "runs": ["r1", "r2", "r3"]}
        storage.download_json.side_effect = [lib_data, quota_data]

        lib = UserLibrary("user-123", storage=storage)
        export = lib.export_all_data()

        assert export["quota"] == quota_data

    def test_export_with_empty_library(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        lib = UserLibrary("user-123", storage=storage)
        export = lib.export_all_data()

        assert export["library"]["kmls"] == []
        assert export["library"]["analyses"] == []
        assert export["user_id"] == "user-123"


# ---------------------------------------------------------------------------
# GDPR — delete_all_data (Article 17)
# ---------------------------------------------------------------------------


class TestDeleteAllData:
    def test_deletes_user_blobs_and_quota(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        storage.list_blobs.return_value = [
            "users/user-123/library.json",
            "users/user-123/kmls/k1.kml",
            "users/user-123/kmls/k2.kml",
        ]

        lib = UserLibrary("user-123", storage=storage)
        result = lib.delete_all_data()

        # 3 user blobs + 1 quota blob = 4
        assert result["blobs_deleted"] == 4
        assert result["user_id"] == "user-123"

        # Verify all blobs deleted
        assert storage.delete_blob.call_count == 4

    def test_delete_with_no_data_returns_zero(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        storage.list_blobs.return_value = []
        storage.delete_blob.return_value = False  # quota blob doesn't exist

        lib = UserLibrary("user-123", storage=storage)
        result = lib.delete_all_data()

        assert result["blobs_deleted"] == 0

    def test_delete_removes_quota_record(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        storage.list_blobs.return_value = []
        storage.delete_blob.return_value = True  # quota exists

        lib = UserLibrary("user-123", storage=storage)
        lib.delete_all_data()

        # Should have tried to delete the quota blob
        storage.delete_blob.assert_called_with("pipeline-payloads", "quotas/user-123.json")

    def test_partial_failure_counts_only_successes(self) -> None:
        from treesight.storage.library import UserLibrary

        storage = _mock_storage()
        storage.list_blobs.return_value = [
            "users/user-123/library.json",
            "users/user-123/kmls/k1.kml",
            "users/user-123/kmls/k2.kml",
        ]
        # First delete succeeds, second fails, third succeeds, quota succeeds
        storage.delete_blob.side_effect = [True, False, True, True]

        lib = UserLibrary("user-123", storage=storage)
        result = lib.delete_all_data()

        # Only 3 succeeded out of 4 attempts
        assert result["blobs_deleted"] == 3

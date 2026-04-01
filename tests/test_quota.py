"""Tests for treesight.security.quota."""

from unittest.mock import MagicMock, patch

import pytest

from treesight.security.quota import FREE_TIER_LIMIT, check_quota, consume_quota, get_usage


@pytest.fixture(autouse=True)
def _mock_storage():
    """Patch BlobStorageClient so quota tests never hit real storage."""
    store: dict[str, dict] = {}
    mock_cls = MagicMock()

    def _download_json(_container, path):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def _upload_json(_container, path, data):
        store[path] = data

    mock_cls.return_value.download_json = _download_json
    mock_cls.return_value.upload_json = _upload_json

    with patch("treesight.storage.client.BlobStorageClient", mock_cls):
        yield store


class TestCheckQuota:
    def test_new_user_has_full_quota(self):
        assert check_quota("user-new") == FREE_TIER_LIMIT

    def test_partial_usage(self, _mock_storage):
        _mock_storage["quotas/user-partial.json"] = {"used": 2, "runs": []}
        assert check_quota("user-partial") == FREE_TIER_LIMIT - 2

    def test_exhausted_returns_zero(self, _mock_storage):
        _mock_storage["quotas/user-full.json"] = {"used": FREE_TIER_LIMIT, "runs": []}
        assert check_quota("user-full") == 0


class TestConsumeQuota:
    def test_first_use(self):
        remaining = consume_quota("user-first")
        assert remaining == FREE_TIER_LIMIT - 1

    def test_successive_uses(self):
        for i in range(FREE_TIER_LIMIT - 1):
            remaining = consume_quota("user-successive")
            assert remaining == FREE_TIER_LIMIT - (i + 1)

    def test_exhaustion_raises(self):
        for _ in range(FREE_TIER_LIMIT):
            consume_quota("user-exhaust")
        with pytest.raises(ValueError, match="Quota exhausted"):
            consume_quota("user-exhaust")

    def test_different_users_independent(self):
        consume_quota("alice")
        consume_quota("alice")
        remaining_bob = consume_quota("bob")
        assert remaining_bob == FREE_TIER_LIMIT - 1


class TestGetUsage:
    def test_new_user_zero_used(self):
        usage = get_usage("user-brand-new")
        assert usage["used"] == 0
        assert usage["limit"] == FREE_TIER_LIMIT

    def test_after_consumption(self):
        consume_quota("user-usage")
        consume_quota("user-usage")
        usage = get_usage("user-usage")
        assert usage["used"] == 2
        assert usage["limit"] == FREE_TIER_LIMIT

    def test_partial_usage_from_store(self, _mock_storage):
        _mock_storage["quotas/user-stored.json"] = {"used": 5, "runs": []}
        usage = get_usage("user-stored")
        assert usage["used"] == 5
        assert usage["limit"] == FREE_TIER_LIMIT


# --- Cosmos path ---


class TestGetQuotaRecordCosmos:
    @patch("treesight.security.quota._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.read_item")
    def test_reads_from_cosmos(self, mock_read, _mock_cosmos):
        mock_read.return_value = {"id": "u1", "quota": {"used": 3, "runs": []}}
        assert check_quota("u1") == FREE_TIER_LIMIT - 3
        mock_read.assert_called_once_with("users", "u1", "u1")

    @patch("treesight.security.quota._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_returns_default_when_cosmos_doc_missing(self, _mock_read, _mock_cosmos):
        assert check_quota("u-new") == FREE_TIER_LIMIT

    @patch("treesight.security.quota._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.read_item", side_effect=RuntimeError("unavailable"))
    def test_falls_back_to_blob_on_cosmos_error(self, _mock_read, _mock_cosmos):
        # Blob storage also empty → default quota
        assert check_quota("u-fallback") == FREE_TIER_LIMIT


class TestSaveQuotaRecordCosmos:
    @patch("treesight.security.quota._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.upsert_item")
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_writes_to_cosmos(self, _mock_read, mock_upsert, _mock_cosmos):
        consume_quota("u1")
        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["id"] == "u1"
        assert doc["quota"]["used"] == 1

    @patch("treesight.security.quota._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.upsert_item", side_effect=RuntimeError("unavailable"))
    @patch("treesight.storage.cosmos.read_item", side_effect=RuntimeError("unavailable"))
    def test_falls_back_to_blob_on_cosmos_write_error(self, _mock_read, _mock_upsert, _mock_cosmos):
        remaining = consume_quota("u-fallback")
        assert remaining == FREE_TIER_LIMIT - 1

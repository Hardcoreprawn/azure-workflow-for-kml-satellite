"""Tests for treesight.security.quota."""

from unittest.mock import MagicMock, patch

import pytest

from treesight.security.quota import FREE_TIER_LIMIT, check_quota, consume_quota


@pytest.fixture(autouse=True)
def _mock_storage():
    """Patch BlobStorageClient so quota tests never hit real storage."""
    store: dict[str, dict] = {}
    etags: dict[str, str] = {}
    _etag_counter = [0]
    mock_cls = MagicMock()

    def _next_etag() -> str:
        _etag_counter[0] += 1
        return f"etag-{_etag_counter[0]}"

    def _download_json(_container, path):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def _download_json_with_etag(_container, path):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path], etags.get(path, "etag-0")

    def _upload_json(_container, path, data):
        store[path] = data
        etags[path] = _next_etag()

    def _upload_json_if_match(_container, path, data, etag):
        current_etag = etags.get(path)
        if current_etag and current_etag != etag:
            from azure.core.exceptions import ResourceModifiedError

            raise ResourceModifiedError("ETag mismatch")
        store[path] = data
        etags[path] = _next_etag()

    mock_cls.return_value.download_json = _download_json
    mock_cls.return_value.download_json_with_etag = _download_json_with_etag
    mock_cls.return_value.upload_json = _upload_json
    mock_cls.return_value.upload_json_if_match = _upload_json_if_match

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
        with pytest.raises(ValueError, match="Free quota exhausted"):
            consume_quota("user-exhaust")

    def test_different_users_independent(self):
        consume_quota("alice")
        consume_quota("alice")
        remaining_bob = consume_quota("bob")
        assert remaining_bob == FREE_TIER_LIMIT - 1

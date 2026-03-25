"""Tests for treesight.security.quota."""

from unittest.mock import MagicMock, patch

import pytest

from treesight.security.quota import FREE_TIER_LIMIT, check_quota, consume_quota


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

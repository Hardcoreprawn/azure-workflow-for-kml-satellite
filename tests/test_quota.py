"""Tests for treesight.security.quota."""

from unittest.mock import patch

import pytest

from treesight.security.quota import (
    FREE_TIER_LIMIT,
    check_quota,
    consume_quota,
    get_usage,
    release_quota,
)


@pytest.fixture(autouse=True)
def _mock_cosmos():
    """Auto-patch Cosmos read_item/upsert_item with in-memory dict store."""
    store: dict[str, dict] = {}  # item_id → document

    def _read_item(container: str, item_id: str, partition_key: str):
        return store.get(f"{container}/{item_id}")

    def _upsert_item(container: str, item: dict):
        store[f"{container}/{item['id']}"] = item
        return item

    with (
        patch("treesight.storage.cosmos.read_item", side_effect=_read_item),
        patch("treesight.storage.cosmos.upsert_item", side_effect=_upsert_item),
    ):
        yield store


class TestCheckQuota:
    def test_new_user_has_full_quota(self):
        assert check_quota("user-new") == FREE_TIER_LIMIT

    def test_partial_usage(self, _mock_cosmos):
        _mock_cosmos["users/user-partial"] = {
            "id": "user-partial",
            "quota": {"used": 2, "runs": []},
        }
        assert check_quota("user-partial") == FREE_TIER_LIMIT - 2

    def test_exhausted_returns_zero(self, _mock_cosmos):
        _mock_cosmos["users/user-full"] = {
            "id": "user-full",
            "quota": {"used": FREE_TIER_LIMIT, "runs": []},
        }
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

    def test_partial_usage_from_store(self, _mock_cosmos):
        _mock_cosmos["users/user-stored"] = {
            "id": "user-stored",
            "quota": {"used": 5, "runs": []},
        }
        usage = get_usage("user-stored")
        assert usage["used"] == 5
        assert usage["limit"] == FREE_TIER_LIMIT


class TestReleaseQuota:
    def test_release_increments_remaining(self):
        consume_quota("user-release")
        consume_quota("user-release")
        remaining = release_quota("user-release")
        assert remaining == FREE_TIER_LIMIT - 1

    def test_release_at_zero_does_not_go_negative(self):
        remaining = release_quota("user-never-used")
        assert remaining == FREE_TIER_LIMIT

    def test_idempotent_with_instance_id(self):
        consume_quota("user-idem")
        consume_quota("user-idem")
        release_quota("user-idem", instance_id="run-abc")
        remaining = release_quota("user-idem", instance_id="run-abc")
        # Second call should be a no-op
        assert remaining == FREE_TIER_LIMIT - 1

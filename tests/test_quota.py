"""Tests for treesight.security.quota."""

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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
    """Auto-patch Cosmos helpers with an in-memory, etag-aware store."""
    from treesight.storage import cosmos as cosmos_mod

    store: dict[str, dict] = {}  # item_id → document
    lock = threading.Lock()

    def _next_etag(current: dict | None) -> str:
        if not current:
            return "1"
        return str(int(current.get("_etag", "0")) + 1)

    def _read_item(container: str, item_id: str, _partition_key: str):
        with lock:
            item = store.get(f"{container}/{item_id}")
            return deepcopy(item) if item is not None else None

    def _upsert_item(container: str, item: dict):
        with lock:
            key = f"{container}/{item['id']}"
            current = store.get(key)
            saved = deepcopy(item)
            saved["_etag"] = _next_etag(current)
            store[key] = saved
            return deepcopy(saved)

    def _read_item_with_etag(container: str, item_id: str, partition_key: str):
        item = _read_item(container, item_id, partition_key)
        if item is None:
            return None
        return item, item.get("_etag", "")

    def _replace_item_with_etag(container: str, item: dict, *, etag: str):
        with lock:
            key = f"{container}/{item['id']}"
            current = store.get(key)
            if not current or current.get("_etag", "") != etag:
                raise cosmos_mod.EtagPreconditionFailedError("simulated conflict")
            saved = deepcopy(item)
            saved["_etag"] = _next_etag(current)
            store[key] = saved
            return deepcopy(saved)

    with (
        patch("treesight.storage.cosmos.read_item", side_effect=_read_item),
        patch("treesight.storage.cosmos.upsert_item", side_effect=_upsert_item),
        patch("treesight.storage.cosmos.read_item_with_etag", side_effect=_read_item_with_etag),
        patch(
            "treesight.storage.cosmos.replace_item_with_etag",
            side_effect=_replace_item_with_etag,
        ),
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

    def test_concurrent_consumption_caps_successes_at_limit(self, _mock_cosmos):
        allowance = 3
        attempts = 10
        user_id = "user-concurrent"

        with patch("treesight.security.quota._run_limit", return_value=allowance):
            with ThreadPoolExecutor(max_workers=attempts) as executor:
                futures = [executor.submit(consume_quota, user_id) for _ in range(attempts)]

        successes = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except ValueError:
                pass

        assert successes == allowance
        assert _mock_cosmos[f"users/{user_id}"]["quota"]["used"] == allowance


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

"""Tests for treesight.security.billing — subscription management."""

from unittest.mock import patch

from treesight.constants import FREE_TIER_RUN_LIMIT, PRO_TIER_RUN_LIMIT
from treesight.security.billing import (
    TEAM_TIER_RUN_LIMIT,
    clear_subscription_emulation,
    get_effective_subscription,
    get_run_limit,
    get_subscription,
    is_pro,
    plan_capabilities,
    save_subscription,
    save_subscription_emulation,
)


class TestGetSubscription:
    @patch("treesight.storage.cosmos.read_item")
    def test_returns_free_default_for_new_user(self, mock_read):
        mock_read.return_value = None
        sub = get_subscription("new-user")
        assert sub["tier"] == "free"
        assert sub["status"] == "none"

    @patch("treesight.storage.cosmos.read_item")
    def test_returns_saved_subscription(self, mock_read):
        mock_read.return_value = {
            "id": "pro-user",
            "user_id": "pro-user",
            "tier": "pro",
            "status": "active",
            "stripe_customer_id": "cus_abc",
            "_ts": 123,
        }
        sub = get_subscription("pro-user")
        assert sub["tier"] == "pro"
        assert sub["status"] == "active"
        assert "_ts" not in sub  # internal fields stripped

    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_returns_default_when_cosmos_doc_missing(self, _mock_read):
        sub = get_subscription("u-new")
        assert sub == {"tier": "free", "status": "none"}


class TestSaveSubscription:
    @patch("treesight.storage.cosmos.upsert_item")
    def test_persists_record(self, mock_upsert):
        save_subscription("user-1", {"tier": "pro", "status": "active"})
        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["id"] == "user-1"
        assert doc["tier"] == "pro"
        assert "updated_at" in doc


class TestGetRunLimit:
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_free_user_gets_free_limit(self, _mock_read):
        assert get_run_limit("free-user") == FREE_TIER_RUN_LIMIT

    @patch("treesight.storage.cosmos.read_item")
    def test_pro_active_gets_pro_limit(self, mock_read):
        mock_read.return_value = {
            "id": "pro-user",
            "tier": "pro",
            "status": "active",
        }
        assert get_run_limit("pro-user") == PRO_TIER_RUN_LIMIT

    @patch("treesight.storage.cosmos.read_item")
    def test_team_active_gets_team_limit(self, mock_read):
        mock_read.return_value = {
            "id": "team-user",
            "tier": "team",
            "status": "active",
        }
        assert get_run_limit("team-user") == TEAM_TIER_RUN_LIMIT

    @patch("treesight.storage.cosmos.read_item")
    def test_pro_past_due_gets_free_limit(self, mock_read):
        mock_read.return_value = {
            "id": "past-due-user",
            "tier": "pro",
            "status": "past_due",
        }
        assert get_run_limit("past-due-user") == FREE_TIER_RUN_LIMIT

    @patch("treesight.storage.cosmos.read_item")
    def test_cancelled_gets_free_limit(self, mock_read):
        mock_read.return_value = {
            "id": "cancelled-user",
            "tier": "free",
            "status": "canceled",
        }
        assert get_run_limit("cancelled-user") == FREE_TIER_RUN_LIMIT


class TestIsPro:
    @patch("treesight.storage.cosmos.read_item")
    def test_active_pro(self, mock_read):
        mock_read.return_value = {
            "id": "pro-user",
            "tier": "pro",
            "status": "active",
        }
        assert is_pro("pro-user") is True

    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_free_user(self, _mock_read):
        assert is_pro("free-user") is False


class TestPlanCapabilities:
    def test_starter_plan_includes_ai(self):
        caps = plan_capabilities("starter")
        assert caps["tier"] == "starter"
        assert caps["run_limit"] == 15
        assert caps["ai_insights"] is True
        assert caps["api_access"] is False


class TestTierEmulation:
    @patch("treesight.storage.cosmos.upsert_item")
    def test_save_emulation_persists_record(self, mock_upsert):
        save_subscription_emulation("user-1", "team")
        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["id"] == "user-1:emulation"
        assert doc["tier"] == "team"
        assert doc["enabled"] is True

    @patch("treesight.storage.cosmos.upsert_item")
    def test_clear_emulation_disables_record(self, mock_upsert):
        clear_subscription_emulation("user-1")
        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["enabled"] is False

    @patch("treesight.storage.cosmos.read_item")
    def test_effective_subscription_prefers_emulated_tier(self, mock_read):
        def _read_item(container, item_id, partition_key):
            if item_id == "user-1":
                return {"id": "user-1", "tier": "free", "status": "none"}
            if item_id == "user-1:emulation":
                return {
                    "id": "user-1:emulation",
                    "enabled": True,
                    "tier": "starter",
                }
            return None

        mock_read.side_effect = _read_item

        effective = get_effective_subscription("user-1")
        assert effective["tier"] == "starter"
        assert effective["status"] == "active"
        assert effective["emulated"] is True

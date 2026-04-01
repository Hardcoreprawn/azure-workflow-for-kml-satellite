"""Tests for treesight.security.billing — subscription management."""

from unittest.mock import MagicMock, patch

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


@patch("treesight.storage.client.BlobStorageClient")
class TestGetSubscription:
    def test_returns_free_default_for_new_user(self, mock_cls):
        mock_cls.return_value.download_json.side_effect = FileNotFoundError
        sub = get_subscription("new-user")
        assert sub["tier"] == "free"
        assert sub["status"] == "none"

    def test_returns_saved_subscription(self, mock_cls):
        mock_cls.return_value.download_json.return_value = {
            "tier": "pro",
            "status": "active",
            "stripe_customer_id": "cus_abc",
        }
        sub = get_subscription("pro-user")
        assert sub["tier"] == "pro"
        assert sub["status"] == "active"


@patch("treesight.storage.client.BlobStorageClient")
class TestSaveSubscription:
    def test_persists_record(self, mock_cls):
        mock_instance = mock_cls.return_value
        save_subscription("user-1", {"tier": "pro", "status": "active"})
        args = mock_instance.upload_json.call_args
        assert args is not None
        saved = args[0][2]
        assert saved["tier"] == "pro"
        assert "updated_at" in saved


@patch("treesight.storage.client.BlobStorageClient")
class TestGetRunLimit:
    def test_free_user_gets_free_limit(self, mock_cls):
        mock_cls.return_value.download_json.side_effect = FileNotFoundError
        assert get_run_limit("free-user") == FREE_TIER_RUN_LIMIT

    def test_pro_active_gets_pro_limit(self, mock_cls):
        mock_cls.return_value.download_json.return_value = {
            "tier": "pro",
            "status": "active",
        }
        assert get_run_limit("pro-user") == PRO_TIER_RUN_LIMIT

    def test_team_active_gets_team_limit(self, mock_cls):
        mock_cls.return_value.download_json.return_value = {
            "tier": "team",
            "status": "active",
        }
        assert get_run_limit("team-user") == TEAM_TIER_RUN_LIMIT

    def test_pro_past_due_gets_free_limit(self, mock_cls):
        mock_cls.return_value.download_json.return_value = {
            "tier": "pro",
            "status": "past_due",
        }
        assert get_run_limit("past-due-user") == FREE_TIER_RUN_LIMIT

    def test_cancelled_gets_free_limit(self, mock_cls):
        mock_cls.return_value.download_json.return_value = {
            "tier": "free",
            "status": "canceled",
        }
        assert get_run_limit("cancelled-user") == FREE_TIER_RUN_LIMIT


@patch("treesight.storage.client.BlobStorageClient")
class TestIsPro:
    def test_active_pro(self, mock_cls):
        mock_cls.return_value.download_json.return_value = {
            "tier": "pro",
            "status": "active",
        }
        assert is_pro("pro-user") is True

    def test_free_user(self, mock_cls):
        mock_cls.return_value.download_json.side_effect = FileNotFoundError
        assert is_pro("free-user") is False


@patch("treesight.storage.client.BlobStorageClient")
class TestPlanCapabilities:
    def test_starter_plan_includes_ai(self, _mock_cls):
        caps = plan_capabilities("starter")
        assert caps["tier"] == "starter"
        assert caps["run_limit"] == 15
        assert caps["ai_insights"] is True
        assert caps["api_access"] is False


@patch("treesight.storage.client.BlobStorageClient")
class TestTierEmulation:
    def test_save_emulation_persists_record(self, mock_cls):
        mock_instance = mock_cls.return_value

        save_subscription_emulation("user-1", "team")

        args = mock_instance.upload_json.call_args
        assert args is not None
        saved = args[0][2]
        assert saved["tier"] == "team"
        assert saved["enabled"] is True

    def test_clear_emulation_disables_record(self, mock_cls):
        mock_instance = mock_cls.return_value

        clear_subscription_emulation("user-1")

        args = mock_instance.upload_json.call_args
        assert args is not None
        saved = args[0][2]
        assert saved["enabled"] is False

    def test_effective_subscription_prefers_emulated_tier(self, mock_cls):
        def _download_json(_container, path):
            if path == "subscriptions/user-1.json":
                return {"tier": "free", "status": "none"}
            if path == "subscription-emulations/user-1.json":
                return {"enabled": True, "tier": "starter"}
            raise FileNotFoundError(path)

        mock_cls.return_value.download_json.side_effect = _download_json

        effective = get_effective_subscription("user-1")
        assert effective["tier"] == "starter"
        assert effective["status"] == "active"
        assert effective["emulated"] is True


# --- Cosmos path ---


class TestGetSubscriptionCosmos:
    @patch("treesight.security.billing._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.read_item")
    def test_reads_from_cosmos(self, mock_read, _mock_cosmos):
        mock_read.return_value = {
            "id": "u1",
            "user_id": "u1",
            "tier": "pro",
            "status": "active",
            "_ts": 123,
        }
        sub = get_subscription("u1")
        mock_read.assert_called_once_with("subscriptions", "u1", "u1")
        assert sub["tier"] == "pro"
        assert "_ts" not in sub  # internal fields stripped

    @patch("treesight.security.billing._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    def test_returns_default_when_cosmos_doc_missing(self, _mock_read, _mock_cosmos):
        sub = get_subscription("u-new")
        assert sub == {"tier": "free", "status": "none"}

    @patch("treesight.storage.client.BlobStorageClient")
    @patch("treesight.security.billing._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.read_item", side_effect=RuntimeError("unavailable"))
    def test_falls_back_to_blob_on_cosmos_error(self, _mock_read, _mock_cosmos, mock_cls):
        mock_cls.return_value.download_json.side_effect = FileNotFoundError
        sub = get_subscription("u-fallback")
        assert sub == {"tier": "free", "status": "none"}


class TestSaveSubscriptionCosmos:
    @patch("treesight.security.billing._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.upsert_item")
    def test_writes_to_cosmos(self, mock_upsert, _mock_cosmos):
        save_subscription("u1", {"tier": "pro", "status": "active"})
        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["id"] == "u1"
        assert doc["tier"] == "pro"

    @patch("treesight.storage.client.BlobStorageClient")
    @patch("treesight.security.billing._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.upsert_item", side_effect=RuntimeError("unavailable"))
    def test_falls_back_to_blob_on_cosmos_write_error(self, _mock_upsert, _mock_cosmos, mock_cls):
        mock_upload = MagicMock()
        mock_cls.return_value.upload_json = mock_upload
        save_subscription("u-fallback", {"tier": "pro", "status": "active"})
        mock_upload.assert_called_once()


class TestEmulationCosmos:
    @patch("treesight.security.billing._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.upsert_item")
    def test_save_emulation_writes_to_cosmos(self, mock_upsert, _mock_cosmos):
        save_subscription_emulation("u1", "starter")
        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["id"] == "u1:emulation"
        assert doc["tier"] == "starter"

    @patch("treesight.security.billing._cosmos_available", return_value=True)
    @patch("treesight.storage.cosmos.upsert_item")
    def test_clear_emulation_writes_to_cosmos(self, mock_upsert, _mock_cosmos):
        clear_subscription_emulation("u1")
        mock_upsert.assert_called_once()
        doc = mock_upsert.call_args[0][1]
        assert doc["enabled"] is False

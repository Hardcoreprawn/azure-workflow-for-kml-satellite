"""Tests for treesight.security.billing — subscription management."""

from unittest.mock import patch

from treesight.constants import FREE_TIER_RUN_LIMIT, PRO_TIER_RUN_LIMIT
from treesight.security.billing import get_run_limit, get_subscription, is_pro, save_subscription


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

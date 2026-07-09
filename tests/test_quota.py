"""Tests for org-pooled quota accounting and migrated quota readers."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

import pytest

from treesight.billing.accounting import finalize_run, get_pool_status, reserve_run
from treesight.security.billing_ledger import billing_fields_for_submission


@pytest.fixture()
def _org_store():
    """In-memory org store with ETag-aware read/replace semantics."""
    from treesight.storage import cosmos as cosmos_mod

    store = {
        "orgs/org-1": {
            "id": "org-1",
            "org_id": "org-1",
            "members": [{"user_id": "user-1", "role": "owner"}],
            "billing": {},
        }
    }
    etags = {"orgs/org-1": "1"}

    def _read_with_etag(container: str, item_id: str, _partition_key: str):
        key = f"{container}/{item_id}"
        item = store.get(key)
        if not item:
            return None
        return deepcopy(item), etags[key]

    def _replace_with_etag(container: str, item: dict, *, etag: str):
        key = f"{container}/{item['id']}"
        if etags.get(key) != etag:
            raise cosmos_mod.EtagPreconditionFailedError("simulated conflict")
        etags[key] = str(int(etags[key]) + 1)
        store[key] = deepcopy(item)
        return deepcopy(store[key])

    def _get_org(org_id: str):
        item = store.get(f"orgs/{org_id}")
        return deepcopy(item) if item else None

    with (
        patch("treesight.storage.cosmos.read_item_with_etag", side_effect=_read_with_etag),
        patch("treesight.storage.cosmos.replace_item_with_etag", side_effect=_replace_with_etag),
        patch("treesight.security.orgs.get_org", side_effect=_get_org),
    ):
        yield store


class TestOrgPooledQuotaGate:
    def test_reserve_and_finalize_failed_drive_pool_usage(self, _org_store):
        with patch("treesight.billing.accounting._member_run_allowance", return_value=5):
            reservation = reserve_run(
                org_id="org-1",
                user_id="user-1",
                parcel_count=1,
                is_eudr=False,
                instance_id="run-1",
            )
            assert reservation.pool_remaining == 4

            status = get_pool_status("org-1")
            assert status["allowance"] == 5
            assert status["reserved"] == 1
            assert status["completed"] == 0
            assert status["available"] == 4

            finalize_run(org_id="org-1", instance_id="run-1", status="failed")
            status_after_fail = get_pool_status("org-1")
            assert status_after_fail["reserved"] == 0
            assert status_after_fail["refunded"] == 1
            assert status_after_fail["available"] == 5

    def test_reserve_and_finalize_completed_drive_completed_counter(self, _org_store):
        with patch("treesight.billing.accounting._member_run_allowance", return_value=5):
            reserve_run(
                org_id="org-1",
                user_id="user-1",
                parcel_count=1,
                is_eudr=False,
                instance_id="run-complete",
            )
            finalize_run(org_id="org-1", instance_id="run-complete", status="completed")

            status = get_pool_status("org-1")
            assert status["reserved"] == 0
            assert status["completed"] == 1
            assert status["refunded"] == 0
            assert status["available"] == 4


class TestOrgPooledReaders:
    @patch("treesight.billing.accounting.compute_pool_allowance", return_value=50)
    @patch("treesight.security.orgs.get_user_org")
    @patch("treesight.security.billing.get_effective_subscription")
    def test_submission_billing_fields_classify_from_org_usage(
        self, mock_sub, mock_get_org, _mock_allowance
    ):
        mock_sub.return_value = {"tier": "pro", "status": "active"}
        mock_get_org.return_value = {
            "org_id": "org-1",
            "usage": {"runs_reserved": 51, "runs_completed": 0},
            "members": [{"user_id": "user-1", "role": "owner"}],
        }

        fields = billing_fields_for_submission("user-1")
        assert fields["tier_at_submission"] == "pro"
        assert fields["billing_type"] == "overage"
        assert fields["overage_unit_price"] == 0.80

    @patch("treesight.billing.accounting.compute_pool_allowance", return_value=50)
    @patch("treesight.security.orgs.get_user_org")
    @patch("treesight.security.billing.get_effective_subscription")
    def test_submission_billing_fields_treat_allowance_boundary_as_included(
        self, mock_sub, mock_get_org, _mock_allowance
    ):
        mock_sub.return_value = {"tier": "pro", "status": "active"}
        mock_get_org.return_value = {
            "org_id": "org-1",
            "usage": {"runs_reserved": 50, "runs_completed": 0},
            "members": [{"user_id": "user-1", "role": "owner"}],
        }

        fields = billing_fields_for_submission("user-1")
        assert fields["billing_type"] == "included"
        assert fields["overage_unit_price"] is None

    @patch("treesight.security.orgs.get_user_org", return_value={"org_id": "org-1"})
    @patch("treesight.storage.cosmos.read_item", return_value=None)
    @patch(
        "treesight.billing.accounting.get_pool_status",
        return_value={
            "org_id": "org-1",
            "allowance": 40,
            "reserved": 7,
            "completed": 11,
            "available": 22,
        },
    )
    def test_billing_status_payload_reads_org_pool_usage(self, _mock_pool, _mock_read, _mock_org):
        from blueprints.billing import _billing_status_payload

        payload = _billing_status_payload("user-1")
        assert payload["runs_used"] == 18
        assert payload["runs_remaining"] == 22

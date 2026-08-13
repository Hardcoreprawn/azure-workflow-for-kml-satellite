"""
End-to-end tests for account management workflows (#830).

Uses real service logic against an in-memory Cosmos mock (via _mock_cosmos).
Covers:
- Create account → Create org → Invite member → Accept invite
- Cross-user token rejection (B3 security fix)
- Profile management (update display name)
- Account deletion (sole-owner guard, ownership transfer)
"""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

from tests.test_org import _apply_patches, _mock_cosmos


class TestAccountCreationAndOrgSetup:
    """Workflow: User signs up and creates organization."""

    def test_user_creates_org_workflow(self):
        """Real: create_org persists org and stamps user doc with membership."""
        from treesight.security.orgs import create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("owner-1", name="Canopex Ltd", email="owner@test.com")

        assert org["name"] == "Canopex Ltd"
        assert len(org["members"]) == 1
        assert org["members"][0]["role"] == "owner"

        user_doc = store.get("users:owner-1")
        assert user_doc is not None
        assert user_doc["org_id"] == org["org_id"]
        assert user_doc["org_role"] == "owner"


class TestOrgInviteAndAcceptance:
    """Workflow: Owner invites member → member accepts via token."""

    def test_invite_and_accept_workflow(self):
        """Real: create org → create invite → accept by token → member joins."""
        from treesight.security.orgs import (
            accept_invite_by_token,
            create_invite,
            create_org,
            list_members,
        )

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("owner-1", name="Test Org", email="owner@test.com")
            invite = create_invite(org["org_id"], "bob@test.com", invited_by="owner-1")

            assert invite["status"] == "pending"
            assert invite["token"]

            # Seed invitee user doc (created on sign-in before accepting).
            store["users:bob-1"] = {
                "id": "bob-1",
                "user_id": "bob-1",
                "email": "bob@test.com",
            }

            accept_invite_by_token(invite["token"], "bob-1")

            members = list_members(org["org_id"])
            assert len(members) == 2
            assert any(m["user_id"] == "bob-1" for m in members)

        # Invite marked accepted (audit trail preserved, not deleted).
        updated_invite = store[f"orgs:{invite['id']}"]
        assert updated_invite["status"] == "accepted"
        assert updated_invite["accepted_by"] == "bob-1"

    def test_cross_user_token_accept_rejected(self):
        """B3: accept_invite_by_token rejects a user whose email != the invite email."""
        from treesight.security.orgs import accept_invite_by_token, create_invite

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            invite = create_invite("org-1", "intended@test.com", invited_by="owner-1")

            # A different user tries to accept the invite using the same token.
            store["users:attacker-1"] = {
                "id": "attacker-1",
                "user_id": "attacker-1",
                "email": "attacker@test.com",
            }

            with pytest.raises(ValueError, match="not issued to your email"):
                accept_invite_by_token(invite["token"], "attacker-1")


class TestProfileManagement:
    """Workflow: User updates profile."""

    def test_user_updates_display_name(self):
        """Real: update_user_profile persists new display name."""
        from treesight.security.users import update_user_profile

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:u1"] = {
            "id": "u1",
            "user_id": "u1",
            "email": "alice@test.com",
            "display_name": "Alice Old",
        }

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            updated = update_user_profile("u1", display_name="Alice New")

        assert updated["display_name"] == "Alice New"
        assert store["users:u1"]["display_name"] == "Alice New"

    def test_profile_update_empty_name_rejected(self):
        """Real: update_user_profile raises ValueError for empty display_name."""
        from treesight.security.users import update_user_profile

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:u1"] = {"id": "u1", "user_id": "u1", "email": "alice@test.com"}

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            with pytest.raises(ValueError, match="must not be empty"):
                update_user_profile("u1", display_name="")

    def test_profile_update_long_name_rejected(self):
        """Real: update_user_profile raises ValueError for names exceeding 200 chars."""
        from treesight.security.users import update_user_profile

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:u1"] = {"id": "u1", "user_id": "u1", "email": "alice@test.com"}

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            with pytest.raises(ValueError, match="\u2264200"):
                update_user_profile("u1", display_name="x" * 201)


class TestAccountDeletionWithTransfer:
    """Workflow: Account deletion — sole-owner guard and ownership transfer."""

    def test_delete_account_sole_owner_without_transfer_raises(self):
        """Real: sole owner cannot delete account without specifying transfer_to."""
        from treesight.security.orgs import add_member, create_org
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("owner-1", email="owner@test.com")
            add_member(org["org_id"], "member-2", email="bob@test.com")

            with pytest.raises(ValueError, match="sole owner"):
                delete_user("owner-1")

    def test_delete_account_with_ownership_transfer(self):
        """Real: ownership promoted to member-2, then owner-1 deleted from all records."""
        from treesight.security.orgs import add_member, create_org
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("owner-1", email="owner@test.com")
            add_member(org["org_id"], "member-2", email="bob@test.com")
            delete_user("owner-1", transfer_to_user_id="member-2")

        # Owner user doc deleted.
        assert store.get("users:owner-1") is None

        # member-2 promoted to owner in the org doc.
        org_doc = store.get(f"orgs:{org['org_id']}")
        members = org_doc["members"]
        new_owner = next((m for m in members if m["user_id"] == "member-2"), None)
        assert new_owner is not None
        assert new_owner["role"] == "owner"

    def test_delete_account_member_no_transfer_needed(self):
        """Real: non-owner member can delete account without specifying transfer_to."""
        from treesight.security.orgs import add_member, create_org
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("owner-1", email="owner@test.com")
            add_member(org["org_id"], "member-2", email="bob@test.com")
            # Seed member-2 user doc so delete_user can remove it.
            store["users:member-2"] = {
                "id": "member-2",
                "user_id": "member-2",
                "email": "bob@test.com",
                "org_id": org["org_id"],
                "org_role": "member",
            }

            delete_user("member-2")

        assert store.get("users:member-2") is None


class TestErasureHardening:
    """GDPR erasure: fail-closed org lookup, partial failure, invite cleanup, billing cancel."""

    def test_org_lookup_failure_aborts_erasure(self):
        """Fail-closed: storage error during org lookup aborts erasure; user doc preserved."""
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "u@test.com"}

        def failing_query(container, query_str, **kwargs):
            if container == "orgs" and "ARRAY_CONTAINS(c.members" in query_str:
                raise RuntimeError("Cosmos connection lost")
            return query(container, query_str, **kwargs)

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, failing_query)
            with pytest.raises(RuntimeError, match="Cosmos connection lost"):
                delete_user("user-1")

        # User doc must survive so erasure can be retried.
        assert store.get("users:user-1") is not None

    def test_partial_run_deletion_failure_preserves_user_doc(self):
        """Run item deletion failure raises RuntimeError; user identity doc is NOT removed."""
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "u@test.com"}
        store["runs:run-bad"] = {"id": "run-bad", "user_id": "user-1"}
        store["runs:run-ok"] = {"id": "run-ok", "user_id": "user-1"}

        original_delete = delete
        call_count = {"n": 0}

        def flaky_delete(container, item_id, partition_key):
            if container == "runs" and item_id == "run-bad":
                call_count["n"] += 1
                raise OSError("transient storage error")
            original_delete(container, item_id, partition_key)

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, flaky_delete, query)
            with pytest.raises(RuntimeError, match="Erasure incomplete"):
                delete_user("user-1")

        # User doc preserved for retry.
        assert store.get("users:user-1") is not None
        # The successful run was still deleted.
        assert store.get("runs:run-ok") is None

    def test_pending_invites_revoked_on_erasure(self):
        """Pending invites sent to the deleted user's email are revoked."""
        from treesight.security.orgs import create_invite, create_org
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "bob@test.com"}

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("owner-1", email="owner@test.com")
            invite = create_invite(org["org_id"], "bob@test.com", invited_by="owner-1")
            assert invite["status"] == "pending"

            delete_user("user-1")

        # Invite must be revoked, not left pending.
        updated_invite = store[f"orgs:{invite['id']}"]
        assert updated_invite["status"] == "revoked"

    def test_active_subscription_cancelled_on_erasure(self):
        """Active subscription is stamped cancelled (not deleted) on account erasure."""
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "u@test.com"}
        store["subscriptions:user-1"] = {
            "id": "user-1",
            "user_id": "user-1",
            "tier": "pro",
            "status": "active",
        }

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            delete_user("user-1")

        sub = store.get("subscriptions:user-1")
        assert sub is not None, "Billing record must be retained"
        assert sub["status"] == "cancelled"
        assert sub["cancelled_reason"] == "gdpr_erasure"

    def test_already_cancelled_subscription_not_double_stamped(self):
        """Erasure of a user with an already-cancelled subscription succeeds cleanly."""
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "u@test.com"}
        store["subscriptions:user-1"] = {
            "id": "user-1",
            "user_id": "user-1",
            "tier": "pro",
            "status": "cancelled",
            "cancelled_reason": "payment_failure",
        }

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            delete_user("user-1")

        # Original cancellation reason preserved.
        sub = store.get("subscriptions:user-1")
        assert sub is not None
        assert sub["cancelled_reason"] == "payment_failure"

    def test_user_doc_deleted_last_after_all_cleanup(self):
        """User document is deleted only after runs and subscriptions are cleaned up."""
        deletion_order = []

        from treesight.security.users import delete_user

        store, upsert, read, orig_delete, query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "u@test.com"}
        store["runs:run-1"] = {"id": "run-1", "user_id": "user-1"}

        def tracked_delete(container, item_id, partition_key):
            deletion_order.append((container, item_id))
            orig_delete(container, item_id, partition_key)

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, tracked_delete, query)
            delete_user("user-1")

        # User document must be the very last deletion.
        assert deletion_order[-1] == ("users", "user-1"), (
            f"User doc was not the last deletion; order was: {deletion_order}"
        )

    def test_run_query_failure_raises_not_swallowed(self):
        """A run query failure during erasure raises and preserves the user doc."""
        from treesight.security.users import delete_user

        store, upsert, read, delete, orig_query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "u@test.com"}

        def failing_query(container, query_str, **kwargs):
            if container == "runs":
                raise RuntimeError("runs query failed")
            return orig_query(container, query_str, **kwargs)

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, failing_query)
            with pytest.raises(RuntimeError, match="runs query failed"):
                delete_user("user-1")

        # User doc preserved for retry.
        assert store.get("users:user-1") is not None

    def test_list_orgs_for_user_strict_raises_on_failure(self):
        """list_orgs_for_user_strict propagates storage errors (fail-closed)."""
        from unittest.mock import patch

        from treesight.security.orgs import list_orgs_for_user_strict

        cosmos_pkg = "treesight.storage.cosmos"
        with (
            patch(f"{cosmos_pkg}.cosmos_available", return_value=True),
            patch(f"{cosmos_pkg}.query_items", side_effect=RuntimeError("network down")),
        ):
            with pytest.raises(RuntimeError, match="network down"):
                list_orgs_for_user_strict("any-user-id")

    def test_list_orgs_for_user_lenient_returns_empty_on_failure(self):
        """list_orgs_for_user (lenient) still returns [] on storage errors."""
        from treesight.security.orgs import list_orgs_for_user

        cosmos_pkg = "treesight.storage.cosmos"
        with (
            patch(f"{cosmos_pkg}.cosmos_available", return_value=True),
            patch(f"{cosmos_pkg}.query_items", side_effect=RuntimeError("network down")),
        ):
            result = list_orgs_for_user("any-user-id")
        assert result == []

    def test_idempotent_retry_after_partial_failure(self):
        """A second erasure call succeeds once the flaky run deletion is fixed."""
        from treesight.security.users import delete_user

        store, upsert, read, delete, query = _mock_cosmos()
        store["users:user-1"] = {"id": "user-1", "user_id": "user-1", "email": "u@test.com"}
        store["runs:run-1"] = {"id": "run-1", "user_id": "user-1"}

        call_count = {"n": 0}
        original_delete = delete

        def flaky_first_delete(container, item_id, partition_key):
            if container == "runs":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise OSError("first attempt fails")
            original_delete(container, item_id, partition_key)

        # First attempt fails.
        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, flaky_first_delete, query)
            with pytest.raises(RuntimeError, match="Erasure incomplete"):
                delete_user("user-1")

        assert store.get("users:user-1") is not None

        # Second attempt succeeds (flaky run deletion now works).
        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            delete_user("user-1")

        assert store.get("users:user-1") is None

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


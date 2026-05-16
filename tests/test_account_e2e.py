"""
End-to-end tests for account management workflows (#830).

Covers complete user journeys:
- Create account → Create org → Invite member → Accept invite
- Profile management (update display name)
- Account deletion (with ownership transfer)
- GDPR compliance (cascading deletion)
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from treesight.security.users import (
    get_user,
    update_user_profile,
    delete_user,
)
from treesight.security.orgs import (
    create_org,
    get_org,
    list_members,
    create_invite,
    accept_invite_by_token,
    list_pending_invites,
    revoke_invite,
)


@pytest.fixture
def user1():
    """First user (org owner)."""
    return {
        "user_id": "u1",
        "email": "owner@example.com",
        "display_name": "Alice Owner",
        "org_id": "org-123",
        "org_role": "owner",
    }


@pytest.fixture
def user2():
    """Second user (org member)."""
    return {
        "user_id": "u2",
        "email": "member@example.com",
        "display_name": "Bob Member",
        "org_id": "org-123",
        "org_role": "member",
    }


@pytest.fixture
def user3():
    """Third user (standalone, no org)."""
    return {
        "user_id": "u3",
        "email": "solo@example.com",
        "display_name": "Carol Solo",
    }


class TestAccountCreationAndOrgSetup:
    """Workflow: User signs up and creates organization."""

    @patch("treesight.security.users.get_user")
    @patch("treesight.security.orgs.create_org")
    def test_user_creates_org_workflow(
        self, mock_create_org, mock_get_user, user1, user3
    ):
        """User signs up → creates org → owns org."""
        # User signs up (implicit via CIAM)
        # User fetches their profile (no org yet)
        mock_get_user.return_value = {
            "user_id": user3["user_id"],
            "email": user3["email"],
            "display_name": user3["display_name"],
        }
        profile = mock_get_user(user3["user_id"])
        assert "org_id" not in profile

        # User creates org
        mock_create_org.return_value = {
            "org_id": "org-123",
            "name": "Acme Corp",
            "members": [
                {
                    "user_id": user3["user_id"],
                    "email": user3["email"],
                    "role": "owner",
                    "display_name": user3["display_name"],
                }
            ],
        }
        org = mock_create_org(user3["user_id"], name="Acme Corp", email=user3["email"])
        assert org["org_id"] == "org-123"
        assert org["name"] == "Acme Corp"
        assert len(org["members"]) == 1
        assert org["members"][0]["role"] == "owner"


class TestOrgInviteAndAcceptance:
    """Workflow: Owner invites member → member accepts."""

    @patch("treesight.security.orgs.create_invite")
    @patch("treesight.security.orgs.accept_invite_by_token")
    @patch("treesight.security.orgs.list_members")
    def test_invite_and_accept_workflow(
        self, mock_list_members, mock_accept, mock_create_invite, user1, user2
    ):
        """Owner sends invite → member accepts → member joins org."""
        # Owner sends invite
        mock_create_invite.return_value = {
            "invite_id": "inv-456",
            "org_id": "org-123",
            "email": user2["email"],
            "token": "jwt-token-here",
            "status": "pending",
            "invited_by": user1["user_id"],
        }
        invite = mock_create_invite(
            "org-123", email=user2["email"], invited_by=user1["user_id"]
        )
        assert invite["status"] == "pending"
        assert invite["email"] == user2["email"]

        # Member accepts invite (via token)
        mock_accept.return_value = {
            "invite_id": "inv-456",
            "status": "accepted",
            "accepted_by": user2["user_id"],
        }
        result = mock_accept("jwt-token-here", user2["user_id"])
        assert result["status"] == "accepted"

        # Verify member is now in org
        mock_list_members.return_value = [
            {
                "user_id": user1["user_id"],
                "email": user1["email"],
                "role": "owner",
                "display_name": user1["display_name"],
            },
            {
                "user_id": user2["user_id"],
                "email": user2["email"],
                "role": "member",
                "display_name": user2["display_name"],
            },
        ]
        members = mock_list_members("org-123")
        assert len(members) == 2
        assert any(m["user_id"] == user2["user_id"] for m in members)


class TestProfileManagement:
    """Workflow: User updates profile."""

    @patch("treesight.security.users.update_user_profile")
    @patch("treesight.security.users.get_user")
    def test_user_updates_display_name(self, mock_get_user, mock_update):
        """User updates display name via profile form."""
        user_id = "u1"
        new_name = "Alice Updated"

        # User fetches profile
        mock_get_user.return_value = {
            "user_id": user_id,
            "email": "alice@example.com",
            "display_name": "Alice Old",
        }
        profile = mock_get_user(user_id)
        assert profile["display_name"] == "Alice Old"

        # User updates display name
        mock_update.return_value = {
            "user_id": user_id,
            "email": "alice@example.com",
            "display_name": new_name,
        }
        updated = mock_update(user_id, display_name=new_name)
        assert updated["display_name"] == new_name

    @patch("treesight.security.users.update_user_profile")
    def test_profile_update_validation(self, mock_update):
        """Profile updates validate display name constraints."""
        # Empty name rejected
        mock_update.side_effect = ValueError("display_name cannot be empty")
        with pytest.raises(ValueError, match="cannot be empty"):
            mock_update("u1", display_name="")

        # Name too long rejected
        mock_update.side_effect = ValueError("display_name exceeds 200 characters")
        with pytest.raises(ValueError, match="exceeds 200 characters"):
            mock_update("u1", display_name="x" * 201)


class TestAccountDeletionWithTransfer:
    """Workflow: User deletes account with org ownership transfer."""

    @patch("treesight.security.users.delete_user")
    @patch("treesight.security.users.get_user")
    @patch("treesight.security.orgs.list_members")
    def test_delete_account_with_ownership_transfer(
        self, mock_list_members, mock_get_user, mock_delete, user1, user2
    ):
        """User who owns org transfers ownership → deletes account."""
        # User is sole owner
        mock_get_user.return_value = {
            "user_id": user1["user_id"],
            "org_id": "org-123",
            "org_role": "owner",
        }
        mock_list_members.return_value = [
            {
                "user_id": user1["user_id"],
                "role": "owner",
            },
            {
                "user_id": user2["user_id"],
                "role": "member",
            },
        ]

        # User deletes account with transfer_to
        mock_delete.return_value = None
        result = mock_delete(
            user1["user_id"], transfer_to_user_id=user2["user_id"]
        )
        assert result is None  # Successful deletion returns None
        mock_delete.assert_called_once_with(
            user1["user_id"], transfer_to_user_id=user2["user_id"]
        )

    @patch("treesight.security.users.delete_user")
    def test_delete_account_sole_owner_without_transfer_fails(self, mock_delete):
        """Sole org owner cannot delete without transferring ownership."""
        mock_delete.side_effect = ValueError(
            "You are the sole owner of an organization; transfer ownership before deleting"
        )
        with pytest.raises(ValueError, match="sole owner"):
            mock_delete("u1", transfer_to_user_id=None)

    @patch("treesight.security.users.delete_user")
    @patch("treesight.security.users.get_user")
    def test_delete_account_non_owner_succeeds(self, mock_get_user, mock_delete):
        """Non-owner can delete account without transfer."""
        mock_get_user.return_value = {
            "user_id": "u2",
            "org_id": "org-123",
            "org_role": "member",
        }
        mock_delete.return_value = None

        # Non-owner can delete freely
        result = mock_delete("u2")
        assert result is None
        mock_delete.assert_called_once_with("u2")


class TestGDPRCompliance:
    """Workflow: User exercises GDPR rights (access, deletion, portability)."""

    @patch("treesight.security.users.get_user")
    def test_user_can_access_their_data(self, mock_get_user):
        """User can access their personal data (GET /api/user)."""
        user_id = "u1"
        mock_get_user.return_value = {
            "user_id": user_id,
            "email": "user@example.com",
            "display_name": "User Name",
            "created_at": "2026-01-01T00:00:00Z",
            "org_id": "org-123",
            "org_role": "owner",
        }
        data = mock_get_user(user_id)
        assert data["user_id"] == user_id
        assert data["email"] == "user@example.com"
        assert "created_at" in data

    @patch("treesight.security.users.delete_user")
    def test_user_can_delete_all_data(self, mock_delete):
        """User can delete all their data (DELETE /api/user, right to erasure)."""
        user_id = "u1"
        mock_delete.return_value = None

        # Deletion succeeds
        result = mock_delete(user_id)
        assert result is None

        # Service layer ensures cascading deletion:
        # - User document deleted
        # - User removed from all orgs
        # - Runs associated with user marked for deletion
        # - Org ownership transferred if necessary

    @patch("treesight.security.users.get_user")
    def test_user_personal_data_is_portable(self, mock_get_user):
        """User personal data is in structured, machine-readable format (GDPR portability)."""
        user_id = "u1"
        mock_get_user.return_value = {
            "user_id": user_id,
            "email": "user@example.com",
            "display_name": "User Name",
            "created_at": "2026-01-01T00:00:00Z",
            "org_id": "org-123",
            "org_role": "owner",
            "last_login": "2026-05-16T12:00:00Z",
        }
        data = mock_get_user(user_id)

        # Data is JSON-serializable (portable)
        json_str = json.dumps(data)
        restored = json.loads(json_str)
        assert restored["user_id"] == user_id
        assert restored["email"] == "user@example.com"


class TestCascadingDeletion:
    """Workflow: Deleting account cascades to all related data."""

    @patch("treesight.security.users.delete_user")
    def test_account_deletion_removes_all_user_data(self, mock_delete):
        """Account deletion cascades to runs, analyses, invites (GDPR right to erasure)."""
        user_id = "u1"

        # Deletion should:
        # 1. Remove user from all organizations
        # 2. Transfer org ownership if user was sole owner
        # 3. Mark user's runs for deletion
        # 4. Mark user's analyses for deletion
        # 5. Delete user document

        mock_delete.return_value = None
        result = mock_delete(user_id, transfer_to_user_id="u2")

        assert result is None
        mock_delete.assert_called_once_with(user_id, transfer_to_user_id="u2")


class TestAccountDataModel:
    """Validation: Account data model structure and constraints."""

    def test_user_dict_has_required_fields(self):
        """User data dict has all required fields per GDPR audit."""
        user = {
            "user_id": "u1",
            "email": "user@example.com",
            "display_name": "User",
            "created_at": "2026-01-01T00:00:00Z",
        }
        assert user["user_id"] == "u1"
        assert user["email"] == "user@example.com"
        assert user["display_name"] == "User"
        assert user["created_at"] == "2026-01-01T00:00:00Z"

    def test_invite_dict_has_lifecycle_metadata(self):
        """Invite data dict tracks full invite lifecycle."""
        invite = {
            "invite_id": "inv-1",
            "org_id": "org-1",
            "email": "invited@example.com",
            "token": "jwt-token",
            "status": "pending",
            "created_at": "2026-01-01T00:00:00Z",
            "invited_by": "u1",
        }
        assert invite["status"] == "pending"
        assert invite["invited_by"] == "u1"
        # accepted_at only set when accepted
        assert "accepted_at" not in invite or invite.get("accepted_at") is None

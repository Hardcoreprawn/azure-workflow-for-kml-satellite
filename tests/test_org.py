"""Tests for org/team data model and service (#614)."""

import json
from contextlib import ExitStack
from unittest.mock import patch

import azure.functions as func
import pytest

_COSMOS_PKG = "treesight.storage.cosmos"


def _mock_cosmos():  # noqa: C901
    """Return mock patches for Cosmos read/write operations."""
    store: dict[str, dict] = {}

    def upsert(container: str, item: dict):
        key = f"{container}:{item['id']}"
        store[key] = item
        return item

    def read(container: str, item_id: str, partition_key: str):
        return store.get(f"{container}:{item_id}")

    def delete(container: str, item_id: str, partition_key: str):
        store.pop(f"{container}:{item_id}", None)

    def query(container: str, query_str: str, **kwargs):  # noqa: C901
        """Mock SQL query — performs basic filtering."""
        results = []
        params = {}

        # Parse parameters from kwargs
        if "parameters" in kwargs:
            for param in kwargs["parameters"]:
                params[param["name"]] = param["value"]

        for key, val in store.items():
            if not key.startswith(f"{container}:"):
                continue

            # Basic filtering logic for common patterns
            matches = True

            # WHERE c.org_id = @org_id
            if "@org_id" in params and val.get("org_id") != params["@org_id"]:
                matches = False

            # WHERE c.doc_type = 'invite'
            if "doc_type = 'invite'" in query_str and val.get("doc_type") != "invite":
                matches = False

            # WHERE c.doc_type = 'org'
            if "doc_type = 'org'" in query_str and val.get("doc_type") != "org":
                matches = False

            # WHERE c.status = 'pending'
            if "c.status = 'pending'" in query_str and val.get("status") != "pending":
                matches = False

            # WHERE LOWER(c.email) = LOWER(@email)
            if "@email" in params:
                val_email = val.get("email", "").lower()
                param_email = params["@email"].lower()
                if val_email != param_email:
                    matches = False

            # ARRAY_CONTAINS(c.members, {user_id: @user_id}, true)
            if "@user_id" in params and "ARRAY_CONTAINS(c.members" in query_str:
                members = val.get("members", [])
                if not any(m.get("user_id") == params["@user_id"] for m in members):
                    matches = False

            if matches:
                results.append(val)

        # Handle ORDER BY
        if "ORDER BY c.invited_at DESC" in query_str:
            results.sort(
                key=lambda x: x.get("invited_at", ""),
                reverse=True,
            )

        return results

    return store, upsert, read, delete, query


def _apply_patches(stack, store, upsert, read, delete, query):
    """Apply all Cosmos mock patches using an ExitStack."""
    stack.enter_context(patch(f"{_COSMOS_PKG}.upsert_item", side_effect=upsert))
    stack.enter_context(patch(f"{_COSMOS_PKG}.read_item", side_effect=read))
    stack.enter_context(patch(f"{_COSMOS_PKG}.delete_item", side_effect=delete))
    stack.enter_context(patch(f"{_COSMOS_PKG}.query_items", side_effect=query))
    stack.enter_context(patch(f"{_COSMOS_PKG}.cosmos_available", return_value=True))


class TestOrgService:
    def test_create_org(self):
        from treesight.security.orgs import create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1", name="Test Corp", email="alice@test.com")

        assert org["name"] == "Test Corp"
        assert org["created_by"] == "user-1"
        assert len(org["members"]) == 1
        assert org["members"][0]["role"] == "owner"
        assert org["members"][0]["email"] == "alice@test.com"

        # User doc should have org_id
        user_doc = store.get("users:user-1")
        assert user_doc is not None
        assert user_doc["org_id"] == org["org_id"]
        assert user_doc["org_role"] == "owner"

    def test_add_member(self):
        from treesight.security.orgs import add_member, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            org = add_member(org["org_id"], "user-2", email="bob@test.com")

        assert len(org["members"]) == 2
        assert org["members"][1]["user_id"] == "user-2"
        assert org["members"][1]["role"] == "member"

    def test_add_duplicate_member_raises(self):
        from treesight.security.orgs import add_member, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            with pytest.raises(ValueError, match="already a member"):
                add_member(org["org_id"], "user-1")

    def test_remove_member(self):
        from treesight.security.orgs import add_member, create_org, remove_member

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            add_member(org["org_id"], "user-2")
            org = remove_member(org["org_id"], "user-2")

        assert len(org["members"]) == 1
        assert org["members"][0]["user_id"] == "user-1"

    def test_cannot_remove_last_owner(self):
        from treesight.security.orgs import create_org, remove_member

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            with pytest.raises(ValueError, match="last owner"):
                remove_member(org["org_id"], "user-1")

    def test_change_role_to_owner(self):
        from treesight.security.orgs import add_member, change_member_role, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            add_member(org["org_id"], "user-2")
            org = change_member_role(org["org_id"], "user-2", "owner")

        owners = [m for m in org["members"] if m["role"] == "owner"]
        assert len(owners) == 2

    def test_cannot_demote_last_owner(self):
        from treesight.security.orgs import change_member_role, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            with pytest.raises(ValueError, match="last owner"):
                change_member_role(org["org_id"], "user-1", "member")

    def test_demote_co_owner(self):
        from treesight.security.orgs import add_member, change_member_role, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            add_member(org["org_id"], "user-2")
            change_member_role(org["org_id"], "user-2", "owner")
            org = change_member_role(org["org_id"], "user-1", "member")

        owners = [m for m in org["members"] if m["role"] == "owner"]
        assert len(owners) == 1
        assert owners[0]["user_id"] == "user-2"

    def test_invalid_role_raises(self):
        from treesight.security.orgs import change_member_role, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            with pytest.raises(ValueError, match="Invalid role"):
                change_member_role(org["org_id"], "user-1", "admin")

    def test_update_org_name(self):
        from treesight.security.orgs import create_org, update_org_name

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            updated = update_org_name(org["org_id"], "New Name")

        assert updated["name"] == "New Name"

    def test_list_members(self):
        from treesight.security.orgs import add_member, create_org, list_members

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            add_member(org["org_id"], "user-2")
            members = list_members(org["org_id"])

        assert len(members) == 2


class TestOrgInvites:
    def test_create_invite(self):
        from treesight.security.orgs import create_invite

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            invite = create_invite("org-1", "bob@test.com", invited_by="user-1")

        assert invite["email"] == "bob@test.com"
        assert invite["org_id"] == "org-1"
        assert invite["doc_type"] == "invite"
        assert invite["status"] == "pending"
        assert invite["token"]  # Should have a token

    def test_accept_invite(self):
        from treesight.security.orgs import accept_invite, create_invite, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            invite = create_invite(org["org_id"], "bob@test.com", invited_by="user-1")
            result = accept_invite(invite, "user-2")

        assert len(result["members"]) == 2
        # Invite should be deleted
        invite_key = f"orgs:{invite['id']}"
        assert invite_key not in store

    def test_create_invite_generates_valid_token(self):
        from treesight.security.orgs import create_invite, validate_invite_token

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            invite = create_invite("org-1", "bob@test.com", invited_by="user-1")

        token = invite["token"]
        payload = validate_invite_token(token)

        assert payload is not None
        assert payload["org_id"] == "org-1"
        assert payload["email"] == "bob@test.com"

    def test_accept_invite_by_token(self):
        from treesight.security.orgs import (
            accept_invite_by_token,
            create_invite,
            create_org,
        )

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            invite = create_invite(org["org_id"], "bob@test.com", invited_by="user-1")
            token = invite["token"]

            # Seed user-2 with matching email (B3: token binds to invitee email).
            store["users:user-2"] = {
                "id": "user-2",
                "user_id": "user-2",
                "email": "bob@test.com",
            }

            result = accept_invite_by_token(token, "user-2")

        assert len(result["members"]) == 2
        assert result["members"][1]["user_id"] == "user-2"

        # Invite should be marked as accepted (not deleted)
        updated_invite = store.get(f"orgs:{invite['id']}")
        assert updated_invite["status"] == "accepted"
        assert updated_invite["accepted_by"] == "user-2"

    def test_accept_invite_with_expired_token_raises(self):
        from unittest.mock import patch

        from treesight.security.orgs import accept_invite_by_token, create_invite, create_org

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            invite = create_invite(org["org_id"], "bob@test.com", invited_by="user-1")
            token = invite["token"]

            # Simulate token expiration by mocking validation
            with patch("treesight.security.orgs.validate_invite_token", return_value=None):
                with pytest.raises(ValueError, match="Invalid or expired"):
                    accept_invite_by_token(token, "user-2")

    def test_revoke_invite(self):
        from treesight.security.orgs import create_invite, revoke_invite

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            invite = create_invite("org-1", "bob@test.com", invited_by="user-1")
            revoke_invite("org-1", "bob@test.com")

        # Invite should be marked as revoked
        updated_invite = store.get(f"orgs:{invite['id']}")
        assert updated_invite["status"] == "revoked"
        assert updated_invite["revoked_at"]

    def test_accept_revoked_invite_raises(self):
        from treesight.security.orgs import (
            accept_invite_by_token,
            create_invite,
            revoke_invite,
        )

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            invite = create_invite("org-1", "bob@test.com", invited_by="user-1")
            revoke_invite("org-1", "bob@test.com")

            # Seed user-2 with matching email (B3: token binds to invitee email).
            store["users:user-2"] = {
                "id": "user-2",
                "user_id": "user-2",
                "email": "bob@test.com",
            }

            with pytest.raises(ValueError, match="revoked"):
                accept_invite_by_token(invite["token"], "user-2")

    def test_list_pending_invites(self):
        from treesight.security.orgs import (
            create_invite,
            list_pending_invites,
            revoke_invite,
        )

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            create_invite("org-1", "bob@test.com", invited_by="user-1")
            create_invite("org-1", "charlie@test.com", invited_by="user-1")
            revoke_invite("org-1", "bob@test.com")

            invites = list_pending_invites("org-1")

        # Only non-revoked invites should be returned
        assert len(invites) == 1
        assert invites[0]["email"] == "charlie@test.com"

    def test_accept_invite_by_token_rejects_superseded_token(self):
        """An original token is rejected after the invite document records a newer one.

        Simulates re-issuance: the stored ``token`` field is overwritten; the
        old JWT (still unexpired) must raise "superseded" so the caller is
        forced to request a fresh invitation.
        """
        from treesight.security.orgs import (
            accept_invite_by_token,
            create_invite,
            create_org,
        )

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")
            invite = create_invite(org["org_id"], "bob@test.com", invited_by="user-1")
            original_token = invite["token"]

            # Simulate re-issuance: overwrite the stored token so it no longer
            # matches the JWT that was issued first.
            stored = store[f"orgs:{invite['id']}"]
            stored["token"] = "different-token-after-reissue"

            # Seed user with matching email
            store["users:user-2"] = {
                "id": "user-2",
                "user_id": "user-2",
                "email": "bob@test.com",
            }

            with pytest.raises(ValueError, match="superseded"):
                accept_invite_by_token(original_token, "user-2")

    def test_create_invite_token_propagates_exception(self):
        """create_invite_token raises when the secret env var is missing.

        Ensures the removed try/except no longer swallows errors.
        """
        import os
        from unittest.mock import patch

        from treesight.security.orgs import create_invite_token

        with patch.dict(os.environ, {}, clear=False):
            # Temporarily unset the secret so _get_invite_secret raises.
            saved = os.environ.pop("INVITE_TOKEN_SECRET", None)
            try:
                with pytest.raises(RuntimeError, match="INVITE_TOKEN_SECRET"):
                    create_invite_token("org-1", "bob@test.com")
            finally:
                if saved is not None:
                    os.environ["INVITE_TOKEN_SECRET"] = saved


class TestListOrgsForUser:
    """F1 — list_orgs_for_user uses correct Cosmos SQL with quoted property names."""

    def test_lists_orgs_for_member(self):
        from treesight.security.orgs import add_member, create_org, list_orgs_for_user

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org1 = create_org("user-1")
            add_member(org1["org_id"], "user-2")
            create_org("user-3", name="Other Org")

            result = list_orgs_for_user("user-2")

        assert len(result) == 1
        assert result[0]["org_id"] == org1["org_id"]

    def test_returns_empty_for_non_member(self):
        from treesight.security.orgs import create_org, list_orgs_for_user

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            create_org("user-1")

            result = list_orgs_for_user("user-99")

        assert result == []

    def test_owner_appears_in_own_org(self):
        from treesight.security.orgs import create_org, list_orgs_for_user

        store, upsert, read, delete, query = _mock_cosmos()

        with ExitStack() as stack:
            _apply_patches(stack, store, upsert, read, delete, query)
            org = create_org("user-1")

            result = list_orgs_for_user("user-1")

        assert len(result) == 1
        assert result[0]["org_id"] == org["org_id"]


class TestOrgInviteListEndpoint:
    """S1 + Q2 — GET /api/org/invites is owner-only."""

    def _make_req(self, user_id: str) -> func.HttpRequest:
        from tests.conftest import TEST_LOCAL_ORIGIN, make_test_request

        return make_test_request(
            url="/api/org/invites",
            method="GET",
            origin=TEST_LOCAL_ORIGIN,
            principal_user_id=user_id,
            auth_header=None,
        )

    @patch("treesight.security.users.get_user", return_value={"org_id": "org-abc"})
    @patch(
        "treesight.security.orgs.get_org",
        return_value={
            "org_id": "org-abc",
            "members": [{"user_id": "owner-user", "role": "owner"}],
        },
    )
    @patch(
        "treesight.security.orgs.list_pending_invites",
        return_value=[{"email": "bob@test.com", "status": "pending"}],
    )
    def test_owner_receives_invite_list(self, _mock_pending, _mock_org, _mock_user):
        from blueprints.org import org_invites_list

        req = self._make_req("owner-user")
        resp = org_invites_list(req)

        assert resp.status_code == 200
        body = json.loads(resp.get_body())
        assert len(body["invites"]) == 1
        assert body["invites"][0]["email"] == "bob@test.com"
        # Token must NOT be exposed in the listing.
        assert "token" not in body["invites"][0]

    @patch("treesight.security.users.get_user", return_value={"org_id": "org-abc"})
    @patch(
        "treesight.security.orgs.get_org",
        return_value={
            "org_id": "org-abc",
            "members": [
                {"user_id": "owner-user", "role": "owner"},
                {"user_id": "member-user", "role": "member"},
            ],
        },
    )
    def test_member_receives_403(self, _mock_org, _mock_user):
        from blueprints.org import org_invites_list

        req = self._make_req("member-user")
        resp = org_invites_list(req)

        assert resp.status_code == 403

    @patch("treesight.security.users.get_user", return_value=None)
    def test_user_without_org_receives_404(self, _mock_user):
        from blueprints.org import org_invites_list

        req = self._make_req("no-org-user")
        resp = org_invites_list(req)

        assert resp.status_code == 404

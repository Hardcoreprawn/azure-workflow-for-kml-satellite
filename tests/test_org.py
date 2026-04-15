"""Tests for org/team data model and service (#614)."""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

_COSMOS_PKG = "treesight.storage.cosmos"


def _mock_cosmos():
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

    def query(container: str, query_str: str, **kwargs):
        results = []
        for key, val in store.items():
            if key.startswith(f"{container}:"):
                results.append(val)
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

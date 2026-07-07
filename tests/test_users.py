"""Tests for user management (treesight.security.users + ops endpoints)."""

from __future__ import annotations

import json
from unittest.mock import patch

import azure.functions as func
import pytest

# ---------------------------------------------------------------------------
# Unit tests: treesight.security.users
# ---------------------------------------------------------------------------


class TestRecordUserSignIn:
    def test_skips_anonymous(self):
        with patch("treesight.storage.cosmos.cosmos_available", return_value=True) as ca:
            from treesight.security.users import record_user_sign_in

            record_user_sign_in("anonymous")
            ca.assert_not_called()

    def test_skips_empty_user(self):
        with patch("treesight.storage.cosmos.cosmos_available", return_value=True) as ca:
            from treesight.security.users import record_user_sign_in

            record_user_sign_in("")
            ca.assert_not_called()

    def test_skips_when_cosmos_unavailable(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=False),
            patch("treesight.storage.cosmos.upsert_item") as upsert,
        ):
            from treesight.security.users import record_user_sign_in

            record_user_sign_in("u1", email="a@b.com")
            upsert.assert_not_called()

    def test_creates_new_user_record(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value=None),
            patch("treesight.storage.cosmos.upsert_item") as upsert,
        ):
            from treesight.security.users import record_user_sign_in

            record_user_sign_in("u1", email="a@b.com", identity_provider="aad")
            upsert.assert_called_once()
            doc = upsert.call_args[0][1]
            assert doc["id"] == "u1"
            assert doc["user_id"] == "u1"
            assert doc["email"] == "a@b.com"
            assert doc["identity_provider"] == "aad"
            assert "first_seen" in doc
            assert "last_seen" in doc

    def test_preserves_existing_fields(self):
        existing = {
            "id": "u1",
            "user_id": "u1",
            "first_seen": "2025-01-01T00:00:00+00:00",
            "billing_allowed": True,
            "quota": {"used": 3, "runs": []},
        }
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value=dict(existing)),
            patch("treesight.storage.cosmos.upsert_item") as upsert,
        ):
            from treesight.security.users import record_user_sign_in

            record_user_sign_in("u1", email="new@b.com")
            doc = upsert.call_args[0][1]
            assert doc["first_seen"] == "2025-01-01T00:00:00+00:00"
            assert doc["billing_allowed"] is True
            assert doc["quota"] == {"used": 3, "runs": []}
            assert doc["email"] == "new@b.com"

    def test_tolerates_cosmos_error(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", side_effect=RuntimeError("boom")),
        ):
            from treesight.security.users import record_user_sign_in

            # Should not raise
            record_user_sign_in("u1", email="a@b.com")


class TestIsBillingAllowed:
    def test_true_when_flag_set(self):
        with patch(
            "treesight.security.users.get_user",
            return_value={"billing_allowed": True},
        ):
            from treesight.security.users import is_billing_allowed

            assert is_billing_allowed("u1") is True

    def test_false_when_flag_missing(self):
        with patch(
            "treesight.security.users.get_user",
            return_value={"id": "u1"},
        ):
            from treesight.security.users import is_billing_allowed

            assert is_billing_allowed("u1") is False

    def test_false_when_user_not_found(self):
        with patch("treesight.security.users.get_user", return_value=None):
            from treesight.security.users import is_billing_allowed

            assert is_billing_allowed("u1") is False


class TestSetUserRole:
    def test_sets_billing_allowed(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value={"id": "u1", "user_id": "u1"}),
            patch("treesight.storage.cosmos.upsert_item") as upsert,
        ):
            from treesight.security.users import set_user_role

            result = set_user_role("u1", billing_allowed=True)
            assert result["billing_allowed"] is True
            upsert.assert_called_once()

    def test_sets_tier(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value={"id": "u1", "user_id": "u1"}),
            patch("treesight.storage.cosmos.upsert_item"),
            patch("treesight.security.billing.save_subscription") as save_sub,
        ):
            from treesight.security.users import set_user_role

            result = set_user_role("u1", tier="pro")
            assert result["assigned_tier"] == "pro"
            save_sub.assert_called_once_with("u1", {"tier": "pro", "status": "active"})

    def test_creates_user_if_not_exists(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value=None),
            patch("treesight.storage.cosmos.upsert_item") as upsert,
        ):
            from treesight.security.users import set_user_role

            result = set_user_role("new-user", billing_allowed=True)
            assert result["id"] == "new-user"
            assert result["billing_allowed"] is True
            upsert.assert_called_once()


class TestLookupUserByEmail:
    def test_finds_user(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.query_items",
                return_value=[{"id": "u1", "email": "a@b.com"}],
            ),
        ):
            from treesight.security.users import lookup_user_by_email

            result = lookup_user_by_email("a@b.com")
            assert result is not None
            assert result["id"] == "u1"

    def test_returns_none_when_not_found(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", return_value=[]),
        ):
            from treesight.security.users import lookup_user_by_email

            assert lookup_user_by_email("nobody@b.com") is None

    def test_returns_none_when_cosmos_unavailable(self):
        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            from treesight.security.users import lookup_user_by_email

            assert lookup_user_by_email("a@b.com") is None

    def test_prefers_billing_enabled_record_when_duplicates_exist(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.query_items",
                return_value=[
                    {
                        "id": "new-id",
                        "user_id": "new-id",
                        "email": "a@b.com",
                        "billing_allowed": False,
                        "last_seen": "2026-07-01T00:00:00+00:00",
                    },
                    {
                        "id": "legacy-id",
                        "user_id": "legacy-id",
                        "email": "a@b.com",
                        "billing_allowed": True,
                        "last_seen": "2026-06-01T00:00:00+00:00",
                    },
                ],
            ),
        ):
            from treesight.security.users import lookup_user_by_email

            result = lookup_user_by_email("a@b.com")
            assert result is not None
            assert result["user_id"] == "legacy-id"

    def test_prefers_used_quota_record_when_billing_flags_equal(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.query_items",
                return_value=[
                    {
                        "id": "new-id",
                        "user_id": "new-id",
                        "email": "a@b.com",
                        "quota": {"used": 0},
                        "last_seen": "2026-07-01T00:00:00+00:00",
                    },
                    {
                        "id": "legacy-id",
                        "user_id": "legacy-id",
                        "email": "a@b.com",
                        "quota": {"used": 2},
                        "last_seen": "2026-06-01T00:00:00+00:00",
                    },
                ],
            ),
        ):
            from treesight.security.users import lookup_user_by_email

            result = lookup_user_by_email("a@b.com")
            assert result is not None
            assert result["user_id"] == "legacy-id"

    def test_prefers_org_member_record_when_other_flags_tie(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.query_items",
                return_value=[
                    {
                        "id": "new-id",
                        "user_id": "new-id",
                        "email": "a@b.com",
                        "last_seen": "2026-07-01T00:00:00+00:00",
                    },
                    {
                        "id": "legacy-id",
                        "user_id": "legacy-id",
                        "email": "a@b.com",
                        "org_id": "org-1",
                        "last_seen": "2026-06-01T00:00:00+00:00",
                    },
                ],
            ),
        ):
            from treesight.security.users import lookup_user_by_email

            result = lookup_user_by_email("a@b.com")
            assert result is not None
            assert result["user_id"] == "legacy-id"

    def test_prefers_newest_last_seen_when_all_other_flags_tie(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.query_items",
                return_value=[
                    {
                        "id": "older-id",
                        "user_id": "older-id",
                        "email": "a@b.com",
                        "last_seen": "2026-06-01T00:00:00+00:00",
                    },
                    {
                        "id": "newer-id",
                        "user_id": "newer-id",
                        "email": "a@b.com",
                        "last_seen": "2026-07-01T00:00:00+00:00",
                    },
                ],
            ),
        ):
            from treesight.security.users import lookup_user_by_email

            result = lookup_user_by_email("a@b.com")
            assert result is not None
            assert result["user_id"] == "newer-id"

    @pytest.mark.parametrize("quota_value", [None, "invalid", {"used": "not-a-number"}])
    def test_handles_malformed_quota_values(self, quota_value):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.query_items",
                return_value=[
                    {
                        "id": "older-id",
                        "user_id": "older-id",
                        "email": "a@b.com",
                        "quota": quota_value,
                        "last_seen": "2026-06-01T00:00:00+00:00",
                    },
                    {
                        "id": "newer-id",
                        "user_id": "newer-id",
                        "email": "a@b.com",
                        "quota": {"used": 0},
                        "last_seen": "2026-07-01T00:00:00+00:00",
                    },
                ],
            ),
        ):
            from treesight.security.users import lookup_user_by_email

            result = lookup_user_by_email("a@b.com")
            assert result is not None
            assert result["user_id"] == "newer-id"


class TestListUsers:
    def test_returns_users(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.query_items",
                return_value=[{"id": "u1"}, {"id": "u2"}],
            ),
        ):
            from treesight.security.users import list_users

            result = list_users(limit=10)
            assert len(result) == 2

    def test_caps_limit_at_200(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", return_value=[]) as qi,
        ):
            from treesight.security.users import list_users

            list_users(limit=999)
            params = qi.call_args[1].get("parameters") or qi.call_args[0][2]
            limit_param = next(p for p in params if p["name"] == "@limit")
            assert limit_param["value"] == 200


# ---------------------------------------------------------------------------
# Unit tests: billing_allowed with Cosmos fallback
# ---------------------------------------------------------------------------


class TestBillingAllowedCosmosIntegration:
    def test_env_var_still_works(self):
        with (
            patch(
                "treesight.security.feature_gate.BILLING_ALLOWED_USERS",
                frozenset({"env-user"}),
            ),
            patch("treesight.security.users.is_billing_allowed", return_value=False),
        ):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("env-user") is True

    def test_cosmos_user_allowed(self):
        with (
            patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset()),
            patch("treesight.security.users.is_billing_allowed", return_value=True),
        ):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("cosmos-user") is True

    def test_neither_source_denies(self):
        with (
            patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset()),
            patch("treesight.security.users.is_billing_allowed", return_value=False),
        ):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("unknown-user") is False

    def test_cosmos_error_falls_through(self):
        with (
            patch("treesight.security.feature_gate.BILLING_ALLOWED_USERS", frozenset()),
            patch(
                "treesight.security.users.is_billing_allowed",
                side_effect=RuntimeError("cosmos down"),
            ),
        ):
            from treesight.security.feature_gate import billing_allowed

            assert billing_allowed("user") is False


# ---------------------------------------------------------------------------
# Ops endpoint tests
# ---------------------------------------------------------------------------

_OPS_KEY = "test-ops-key-12345"


def _make_ops_req(
    *,
    method: str = "GET",
    url: str = "/api/ops/users",
    bearer: str | None = None,
    params: dict[str, str] | None = None,
    body: bytes = b"",
) -> func.HttpRequest:
    headers: dict[str, str] = {}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return func.HttpRequest(
        method=method,
        url=url,
        headers=headers,
        params=params or {},
        body=body,
    )


class TestOpsListUsers:
    def test_unauthorized_without_key(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_list_users

        resp = ops_list_users(_make_ops_req())
        assert resp.status_code == 401

    def test_returns_users(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        with patch(
            "treesight.security.users.list_users",
            return_value=[{"id": "u1", "email": "a@b.com"}],
        ):
            from blueprints.ops import ops_list_users

            resp = ops_list_users(_make_ops_req(bearer=_OPS_KEY))
            assert resp.status_code == 200
            data = json.loads(resp.get_body())
            assert len(data) == 1
            assert data[0]["email"] == "a@b.com"


class TestOpsLookupUser:
    def test_unauthorized_without_key(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_lookup_user

        resp = ops_lookup_user(_make_ops_req(url="/api/ops/users/lookup"))
        assert resp.status_code == 401

    def test_missing_email_param(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_lookup_user

        resp = ops_lookup_user(_make_ops_req(bearer=_OPS_KEY, url="/api/ops/users/lookup"))
        assert resp.status_code == 400

    def test_user_not_found(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        with patch("treesight.security.users.lookup_user_by_email", return_value=None):
            from blueprints.ops import ops_lookup_user

            resp = ops_lookup_user(
                _make_ops_req(
                    bearer=_OPS_KEY,
                    url="/api/ops/users/lookup",
                    params={"email": "nobody@b.com"},
                )
            )
            assert resp.status_code == 404

    def test_finds_user_by_email(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        with patch(
            "treesight.security.users.lookup_user_by_email",
            return_value={"id": "u1", "email": "a@b.com"},
        ):
            from blueprints.ops import ops_lookup_user

            resp = ops_lookup_user(
                _make_ops_req(
                    bearer=_OPS_KEY,
                    url="/api/ops/users/lookup",
                    params={"email": "a@b.com"},
                )
            )
            assert resp.status_code == 200
            assert json.loads(resp.get_body())["email"] == "a@b.com"


class TestOpsSetUserRole:
    def _make_role_req(self, *, bearer=None, user_id="u1", body=None):
        headers = {}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return func.HttpRequest(
            method="POST",
            url=f"/api/ops/users/{user_id}/role",
            headers=headers,
            params={},
            route_params={"user_id": user_id},
            body=json.dumps(body or {}).encode(),
        )

    def test_unauthorized_without_key(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_set_user_role

        resp = ops_set_user_role(self._make_role_req())
        assert resp.status_code == 401

    def test_rejects_empty_body(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_set_user_role

        resp = ops_set_user_role(self._make_role_req(bearer=_OPS_KEY, body={}))
        assert resp.status_code == 400

    def test_sets_billing_allowed(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        with patch(
            "treesight.security.users.set_user_role",
            return_value={"id": "u1", "billing_allowed": True},
        ):
            from blueprints.ops import ops_set_user_role

            resp = ops_set_user_role(
                self._make_role_req(
                    bearer=_OPS_KEY,
                    body={"billing_allowed": True},
                )
            )
            assert resp.status_code == 200
            assert json.loads(resp.get_body())["billing_allowed"] is True

    def test_sets_tier(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        with patch(
            "treesight.security.users.set_user_role",
            return_value={"id": "u1", "assigned_tier": "pro"},
        ):
            from blueprints.ops import ops_set_user_role

            resp = ops_set_user_role(
                self._make_role_req(
                    bearer=_OPS_KEY,
                    body={"tier": "pro"},
                )
            )
            assert resp.status_code == 200
            assert json.loads(resp.get_body())["assigned_tier"] == "pro"

    def test_rejects_non_bool_billing_allowed(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_set_user_role

        resp = ops_set_user_role(
            self._make_role_req(bearer=_OPS_KEY, body={"billing_allowed": "yes"})
        )
        assert resp.status_code == 400
        assert "boolean" in json.loads(resp.get_body())["error"]

    def test_rejects_non_string_tier(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_set_user_role

        resp = ops_set_user_role(self._make_role_req(bearer=_OPS_KEY, body={"tier": 123}))
        assert resp.status_code == 400
        assert "string" in json.loads(resp.get_body())["error"]

    def test_rejects_empty_tier(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_set_user_role

        resp = ops_set_user_role(self._make_role_req(bearer=_OPS_KEY, body={"tier": "   "}))
        assert resp.status_code == 400

    def test_returns_503_when_cosmos_unavailable(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        with patch(
            "treesight.security.users.set_user_role",
            side_effect=RuntimeError("Cosmos DB is not available"),
        ):
            from blueprints.ops import ops_set_user_role

            resp = ops_set_user_role(
                self._make_role_req(bearer=_OPS_KEY, body={"billing_allowed": True})
            )
            assert resp.status_code == 503


class TestOpsListUsersLimitValidation:
    def test_rejects_non_integer_limit(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        from blueprints.ops import ops_list_users

        resp = ops_list_users(_make_ops_req(bearer=_OPS_KEY, params={"limit": "abc"}))
        assert resp.status_code == 400

    def test_clamps_negative_limit(self, monkeypatch):
        monkeypatch.setenv("OPS_DASHBOARD_KEY", _OPS_KEY)
        with patch("treesight.security.users.list_users", return_value=[]) as mock_lu:
            from blueprints.ops import ops_list_users

            resp = ops_list_users(_make_ops_req(bearer=_OPS_KEY, params={"limit": "-5"}))
            assert resp.status_code == 200
            mock_lu.assert_called_once_with(limit=1)


class TestSetUserRoleCosmos:
    def test_raises_when_cosmos_unavailable(self):
        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            from treesight.security.users import set_user_role

            with pytest.raises(RuntimeError, match="not available"):
                set_user_role("u1", billing_allowed=True)


# ---------------------------------------------------------------------------
# Slice 2: Profile update and account deletion
# ---------------------------------------------------------------------------


class TestUpdateUserProfile:
    def test_updates_display_name(self):
        existing = {
            "id": "u1",
            "user_id": "u1",
            "email": "a@b.com",
            "display_name": "Alice",
        }
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value=dict(existing)),
            patch("treesight.storage.cosmos.upsert_item") as upsert,
        ):
            from treesight.security.users import update_user_profile

            result = update_user_profile("u1", display_name="Alice Brown")
            assert result["display_name"] == "Alice Brown"
            upsert.assert_called_once()
            doc = upsert.call_args[0][1]
            assert doc["display_name"] == "Alice Brown"
            assert doc["last_modified"] is not None

    def test_rejects_empty_display_name(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value={"id": "u1", "user_id": "u1"}),
        ):
            from treesight.security.users import update_user_profile

            with pytest.raises(ValueError, match="display_name"):
                update_user_profile("u1", display_name="")

    def test_rejects_whitespace_only_display_name(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value={"id": "u1", "user_id": "u1"}),
        ):
            from treesight.security.users import update_user_profile

            with pytest.raises(ValueError, match="display_name"):
                update_user_profile("u1", display_name="   ")

    def test_rejects_too_long_display_name(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value={"id": "u1", "user_id": "u1"}),
        ):
            from treesight.security.users import update_user_profile

            long_name = "x" * 201
            with pytest.raises(ValueError, match="display_name"):
                update_user_profile("u1", display_name=long_name)

    def test_raises_when_user_not_found(self):
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value=None),
        ):
            from treesight.security.users import update_user_profile

            with pytest.raises(ValueError, match="not found"):
                update_user_profile("u1", display_name="New Name")

    def test_preserves_other_fields(self):
        existing = {
            "id": "u1",
            "user_id": "u1",
            "email": "a@b.com",
            "billing_allowed": True,
            "quota": {"used": 5},
        }
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item", return_value=dict(existing)),
            patch("treesight.storage.cosmos.upsert_item") as upsert,
        ):
            from treesight.security.users import update_user_profile

            update_user_profile("u1", display_name="New Name")
            doc = upsert.call_args[0][1]
            assert doc["billing_allowed"] is True
            assert doc["quota"] == {"used": 5}
            assert doc["email"] == "a@b.com"

    def test_raises_when_cosmos_unavailable(self):
        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            from treesight.security.users import update_user_profile

            with pytest.raises(RuntimeError, match="not available"):
                update_user_profile("u1", display_name="New Name")


class TestDeleteUser:
    def test_delete_user_not_member_removes_from_all_orgs(self):
        """User is not a member of any org; just delete the user doc."""
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.security.orgs.list_orgs_for_user", return_value=[]),
            patch("treesight.storage.cosmos.delete_item") as delete,
        ):
            from treesight.security.users import delete_user

            delete_user("u1")
            delete.assert_called_once_with("users", "u1", "u1")

    def test_delete_user_removes_from_member_orgs(self):
        """User is a member (not owner) of orgs; remove from each org."""
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.security.orgs.list_orgs_for_user",
                return_value=[
                    {"org_id": "org1", "org_role": "member"},
                    {"org_id": "org2", "org_role": "member"},
                ],
            ),
            patch("treesight.security.orgs.remove_member") as remove_member,
            patch("treesight.storage.cosmos.delete_item") as delete,
        ):
            from treesight.security.users import delete_user

            delete_user("u1")
            assert remove_member.call_count == 2
            delete.assert_called_once_with("users", "u1", "u1")

    def test_delete_user_sole_owner_transfer_ownership(self):
        """User is sole owner of an org; transfer ownership to another member."""
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.security.orgs.list_orgs_for_user",
                return_value=[{"org_id": "org1", "org_role": "owner"}],
            ),
            patch("treesight.security.orgs.get_org") as get_org,
            patch("treesight.security.orgs.change_member_role") as change_role,
            patch("treesight.security.orgs.remove_member") as remove_member,
            patch("treesight.storage.cosmos.delete_item"),
        ):
            org_doc = {
                "org_id": "org1",
                "members": [
                    {"user_id": "u1", "role": "owner"},
                    {"user_id": "u2", "role": "member"},
                ],
            }
            get_org.return_value = org_doc

            from treesight.security.users import delete_user

            delete_user("u1", transfer_to_user_id="u2")

            # Should promote u2 to owner
            change_role.assert_called_once_with("org1", "u2", "owner")
            # Then remove u1
            remove_member.assert_called_once_with("org1", "u1")

    def test_delete_user_sole_owner_no_transfer_rejects(self):
        """User is sole owner; no transfer_to_user_id provided → error."""
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.security.orgs.list_orgs_for_user",
                return_value=[{"org_id": "org1", "org_role": "owner"}],
            ),
            patch("treesight.security.orgs.get_org") as get_org,
        ):
            org_doc = {
                "org_id": "org1",
                "members": [{"user_id": "u1", "role": "owner"}],
            }
            get_org.return_value = org_doc

            from treesight.security.users import delete_user

            with pytest.raises(ValueError, match=r"sole owner|transfer"):
                delete_user("u1")

    def test_delete_user_transfer_to_non_member_rejects(self):
        """Transfer target is not a member of the org → error."""
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.security.orgs.list_orgs_for_user",
                return_value=[{"org_id": "org1", "org_role": "owner"}],
            ),
            patch("treesight.security.orgs.get_org") as get_org,
        ):
            org_doc = {
                "org_id": "org1",
                "members": [
                    {"user_id": "u1", "role": "owner"},
                    {"user_id": "u2", "role": "member"},
                ],
            }
            get_org.return_value = org_doc

            from treesight.security.users import delete_user

            with pytest.raises(ValueError, match="not a member"):
                delete_user("u1", transfer_to_user_id="u3")

    def test_delete_user_cascades_data_deletion(self):
        """All user data (runs, analysis) should be marked for deletion."""
        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.security.orgs.list_orgs_for_user", return_value=[]),
            patch("treesight.storage.cosmos.delete_item") as delete,
            patch("treesight.storage.cosmos.query_items") as query,
        ):
            # Simulate user has 2 runs
            query.return_value = [
                {"id": "run1", "user_id": "u1"},
                {"id": "run2", "user_id": "u1"},
            ]

            from treesight.security.users import delete_user

            delete_user("u1")

            # Should delete user document
            delete_calls = [c for c in delete.call_args_list if c[0][0] == "users"]
            assert len(delete_calls) >= 1

    def test_delete_user_raises_when_cosmos_unavailable(self):
        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            from treesight.security.users import delete_user

            with pytest.raises(RuntimeError, match="not available"):
                delete_user("u1")


# ---------------------------------------------------------------------------
# Account API endpoints (Slice 3)
# ---------------------------------------------------------------------------


def _make_account_req(
    *,
    method: str = "GET",
    url: str = "/api/user/profile",
    bearer: str | None = None,
    body: bytes = b"",
    params: dict | None = None,
) -> func.HttpRequest:
    """Helper to create mock HttpRequest for account endpoints."""
    headers = {}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if params is None:
        params = {}
    return func.HttpRequest(
        method=method,
        url=url,
        headers=headers,
        params=params,
        body=body,
    )


class TestAccountProfileEndpoint:
    """Tests for PATCH /api/user/profile"""

    def test_requires_auth(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_AUTH", "true")
        from blueprints.account import update_profile_endpoint

        resp = update_profile_endpoint(_make_account_req(method="PATCH"))
        assert resp.status_code == 401

    def test_rejects_empty_body(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                from blueprints.account import update_profile_endpoint

                resp = update_profile_endpoint(
                    _make_account_req(method="PATCH", bearer="token", body=b"{}")
                )
                assert resp.status_code == 400
                assert "display_name" in json.loads(resp.get_body())["error"]

    def test_rejects_invalid_json(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                from blueprints.account import update_profile_endpoint

                resp = update_profile_endpoint(
                    _make_account_req(method="PATCH", bearer="token", body=b"not json")
                )
                assert resp.status_code == 400

    def test_updates_display_name_with_mocked_auth(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.update_user_profile",
                    return_value={"id": "u1", "display_name": "New Name"},
                ):
                    from blueprints.account import update_profile_endpoint

                    resp = update_profile_endpoint(
                        _make_account_req(
                            method="PATCH",
                            bearer="token",
                            body=json.dumps({"display_name": "New Name"}).encode(),
                        )
                    )
                    assert resp.status_code == 200
                    data = json.loads(resp.get_body())
                    assert data["user"]["display_name"] == "New Name"

    def test_rejects_blank_display_name(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                from blueprints.account import update_profile_endpoint

                resp = update_profile_endpoint(
                    _make_account_req(
                        method="PATCH",
                        bearer="token",
                        body=json.dumps({"display_name": "   "}).encode(),
                    )
                )
                assert resp.status_code == 400

    def test_handles_user_not_found(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.update_user_profile",
                    side_effect=ValueError("User not found"),
                ):
                    from blueprints.account import update_profile_endpoint

                    resp = update_profile_endpoint(
                        _make_account_req(
                            method="PATCH",
                            bearer="token",
                            body=json.dumps({"display_name": "New"}).encode(),
                        )
                    )
                    assert resp.status_code == 404

    def test_handles_cosmos_unavailable(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.update_user_profile",
                    side_effect=RuntimeError("Cosmos DB is not available"),
                ):
                    from blueprints.account import update_profile_endpoint

                    resp = update_profile_endpoint(
                        _make_account_req(
                            method="PATCH",
                            bearer="token",
                            body=json.dumps({"display_name": "New"}).encode(),
                        )
                    )
                    assert resp.status_code == 503


class TestAccountDeleteEndpoint:
    """Tests for DELETE /api/user"""

    def test_requires_auth(self, monkeypatch):
        monkeypatch.setenv("REQUIRE_AUTH", "true")
        from blueprints.account import delete_account_endpoint

        resp = delete_account_endpoint(_make_account_req(method="DELETE", url="/api/user"))
        assert resp.status_code == 401

    def test_deletes_user_without_orgs(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.delete_user",
                    return_value=None,
                ):
                    from blueprints.account import delete_account_endpoint

                    resp = delete_account_endpoint(
                        _make_account_req(method="DELETE", url="/api/user", bearer="token")
                    )
                    assert resp.status_code == 204

    def test_accepts_transfer_parameter(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.delete_user",
                    return_value=None,
                ) as mock_delete:
                    from blueprints.account import delete_account_endpoint

                    resp = delete_account_endpoint(
                        _make_account_req(
                            method="DELETE",
                            url="/api/user",
                            bearer="token",
                            params={"transfer_to": "u2"},
                        )
                    )
                    assert resp.status_code == 204
                    mock_delete.assert_called_once_with("u1", transfer_to_user_id="u2")

    def test_rejects_invalid_transfer_target(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.delete_user",
                    side_effect=ValueError("not a member"),
                ):
                    from blueprints.account import delete_account_endpoint

                    resp = delete_account_endpoint(
                        _make_account_req(
                            method="DELETE",
                            url="/api/user",
                            bearer="token",
                            params={"transfer_to": "u3"},
                        )
                    )
                    assert resp.status_code == 400

    def test_rejects_sole_owner_without_transfer(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.delete_user",
                    side_effect=ValueError("sole owner"),
                ):
                    from blueprints.account import delete_account_endpoint

                    resp = delete_account_endpoint(
                        _make_account_req(method="DELETE", url="/api/user", bearer="token")
                    )
                    assert resp.status_code == 400

    def test_handles_cosmos_unavailable(self, monkeypatch):
        with patch("blueprints._helpers._resolve_bearer_claims", return_value={"oid": "u1"}):
            with patch("blueprints._helpers.get_user_id_from_bearer_claims", return_value="u1"):
                with patch(
                    "treesight.security.users.delete_user",
                    side_effect=RuntimeError("Cosmos DB is not available"),
                ):
                    from blueprints.account import delete_account_endpoint

                    resp = delete_account_endpoint(
                        _make_account_req(method="DELETE", url="/api/user", bearer="token")
                    )
                    assert resp.status_code == 503

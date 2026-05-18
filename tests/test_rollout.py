"""Tests for the generalised feature flag evaluator (treesight.security.rollout).

Spec reference: docs/PRODUCTION_ROLLOUT_SPEC.md §6 Feature Evaluation Rules.

Evaluation order (strict):
  1. kill_switch → disabled
  2. missing/unreadable doc → disabled
  3. valid per-user override → override decision
  4. status off/blocked → disabled
  5. status preview_only → enabled only for explicit preview overrides
  6. status percentage_rollout → deterministic bucket check
  7. status on → enabled
"""

from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bucket(feature_name: str, user_id: str) -> int:
    """Reproduce the spec §6.3 bucketing formula."""
    h = hashlib.sha256(f"{feature_name}:{user_id}".encode()).hexdigest()
    return int(h, 16) % 100


def _make_flag(status: str = "on", **kwargs) -> dict:
    base = {
        "id": "test-feature",
        "feature_name": "test-feature",
        "status": status,
        "kill_switch": False,
        "preview_enabled": False,
        "rollout_pct": 0,
        "allow_anonymous": False,
    }
    base.update(kwargs)
    return base


def _make_override(user_id: str, feature_name: str, enabled: bool) -> dict:
    return {
        "id": user_id,
        "user_id": user_id,
        "features": {
            feature_name: {"enabled": enabled},
        },
    }


# ---------------------------------------------------------------------------
# Fixtures / patches
# ---------------------------------------------------------------------------


FEATURE = "test-feature"
USER = "user-abc"


def _patch_flag(flag_doc, override_doc=None):
    """Context manager that patches the two Cosmos reads used by is_feature_enabled."""
    from treesight.security import rollout as r

    def fake_read_flag(name):
        return flag_doc

    def fake_read_override(user_id):
        return override_doc

    return (
        patch.object(r, "_read_flag", side_effect=fake_read_flag),
        patch.object(r, "_read_override", side_effect=fake_read_override),
    )


# ---------------------------------------------------------------------------
# Rule 1: kill_switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_kill_switch_disables_even_when_on(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on", kill_switch=True)
        p1, p2 = _patch_flag(flag)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is False

    def test_no_kill_switch_allows_on(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on", kill_switch=False)
        p1, p2 = _patch_flag(flag)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is True


# ---------------------------------------------------------------------------
# Rule 2: missing / unreadable document → disabled (fail closed)
# ---------------------------------------------------------------------------


class TestMissingDoc:
    def test_missing_flag_returns_false(self):
        from treesight.security.rollout import is_feature_enabled

        p1, p2 = _patch_flag(None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is False

    def test_cosmos_exception_returns_false(self):
        from treesight.security import rollout as r
        from treesight.security.rollout import is_feature_enabled

        with (
            patch.object(r, "_read_flag", side_effect=Exception("cosmos down")),
            patch.object(r, "_read_override", return_value=None),
        ):
            assert is_feature_enabled(FEATURE, USER) is False

    def test_override_read_exception_is_conservative(self):
        from treesight.security import rollout as r
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on")
        # Override read blows up; should still fail closed on the override path
        # but continue to evaluate (no override means fall through to status).
        with (
            patch.object(r, "_read_flag", return_value=flag),
            patch.object(r, "_read_override", side_effect=Exception("cosmos down")),
        ):
            # flag is "on" and override is unreadable → treat as no override → enabled
            assert is_feature_enabled(FEATURE, USER) is True


# ---------------------------------------------------------------------------
# Rule 3: per-user override
# ---------------------------------------------------------------------------


class TestPerUserOverride:
    def test_override_enabled_beats_off_flag(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="off")
        override = _make_override(USER, FEATURE, enabled=True)
        p1, p2 = _patch_flag(flag, override)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is True

    def test_override_disabled_beats_on_flag(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on")
        override = _make_override(USER, FEATURE, enabled=False)
        p1, p2 = _patch_flag(flag, override)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is False

    def test_override_for_different_feature_is_ignored(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="off")
        override = _make_override(USER, "other-feature", enabled=True)
        p1, p2 = _patch_flag(flag, override)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is False

    def test_no_override_falls_through(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on")
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is True

    def test_override_respected_before_kill_switch_check(self):
        """kill_switch must still win over a positive override."""
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on", kill_switch=True)
        override = _make_override(USER, FEATURE, enabled=True)
        p1, p2 = _patch_flag(flag, override)
        with p1, p2:
            # kill_switch is rule 1; override is rule 3; kill_switch wins
            assert is_feature_enabled(FEATURE, USER) is False


# ---------------------------------------------------------------------------
# Rule 4: status off / blocked
# ---------------------------------------------------------------------------


class TestStatusOffBlocked:
    @pytest.mark.parametrize("status", ["off", "blocked"])
    def test_off_and_blocked_return_false(self, status):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status=status)
        p1, p2 = _patch_flag(flag)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is False


# ---------------------------------------------------------------------------
# Rule 5: preview_only
# ---------------------------------------------------------------------------


class TestPreviewOnly:
    def test_preview_only_without_override_returns_false(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="preview_only")
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is False

    def test_preview_only_with_enabled_override_returns_true(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="preview_only")
        override = _make_override(USER, FEATURE, enabled=True)
        p1, p2 = _patch_flag(flag, override)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is True

    def test_preview_only_blocks_anonymous(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="preview_only", allow_anonymous=False)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, "anonymous") is False

    def test_preview_only_blocks_none_user(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="preview_only")
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, None) is False


# ---------------------------------------------------------------------------
# Rule 6: percentage_rollout
# ---------------------------------------------------------------------------


class TestPercentageRollout:
    def _user_in_bucket(self, feature: str, rollout_pct: int) -> str | None:
        """Find a user_id whose bucket falls within rollout_pct."""
        for i in range(200):
            uid = f"user-{i}"
            if _bucket(feature, uid) < rollout_pct:
                return uid
        return None

    def _user_outside_bucket(self, feature: str, rollout_pct: int) -> str | None:
        """Find a user_id whose bucket falls outside rollout_pct."""
        for i in range(200):
            uid = f"user-{i}"
            if _bucket(feature, uid) >= rollout_pct:
                return uid
        return None

    def test_user_in_bucket_enabled(self):
        from treesight.security.rollout import is_feature_enabled

        rollout_pct = 50
        uid = self._user_in_bucket(FEATURE, rollout_pct)
        assert uid is not None, "could not find an in-bucket user"

        flag = _make_flag(status="percentage_rollout", rollout_pct=rollout_pct)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, uid) is True

    def test_user_outside_bucket_disabled(self):
        from treesight.security.rollout import is_feature_enabled

        rollout_pct = 50
        uid = self._user_outside_bucket(FEATURE, rollout_pct)
        assert uid is not None, "could not find an outside-bucket user"

        flag = _make_flag(status="percentage_rollout", rollout_pct=rollout_pct)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, uid) is False

    def test_zero_pct_disables_all(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="percentage_rollout", rollout_pct=0)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            for i in range(20):
                assert is_feature_enabled(FEATURE, f"user-{i}") is False

    def test_100_pct_enables_all(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="percentage_rollout", rollout_pct=100)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            for i in range(20):
                assert is_feature_enabled(FEATURE, f"user-{i}") is True

    def test_bucketing_is_deterministic(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="percentage_rollout", rollout_pct=50)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            first_call = is_feature_enabled(FEATURE, USER)

        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            second_call = is_feature_enabled(FEATURE, USER)

        assert first_call == second_call

    def test_override_beats_percentage_rollout(self):
        from treesight.security.rollout import is_feature_enabled

        rollout_pct = 0  # nobody gets in via bucket
        uid = "user-forced"
        flag = _make_flag(status="percentage_rollout", rollout_pct=rollout_pct)
        override = _make_override(uid, FEATURE, enabled=True)
        p1, p2 = _patch_flag(flag, override)
        with p1, p2:
            assert is_feature_enabled(FEATURE, uid) is True


# ---------------------------------------------------------------------------
# Rule 7: status on
# ---------------------------------------------------------------------------


class TestStatusOn:
    def test_on_enables_for_any_authenticated_user(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on")
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, USER) is True

    def test_on_with_allow_anonymous_enables_for_anon(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on", allow_anonymous=True)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, "anonymous") is True

    def test_on_without_allow_anonymous_blocks_anon(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on", allow_anonymous=False)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, "anonymous") is False


# ---------------------------------------------------------------------------
# Anonymous / None user handling
# ---------------------------------------------------------------------------


class TestAnonymousUser:
    @pytest.mark.parametrize("user_id", [None, "anonymous"])
    def test_anonymous_gated_by_default(self, user_id):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on", allow_anonymous=False)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, user_id) is False

    def test_anonymous_allowed_when_flag_permits(self):
        from treesight.security.rollout import is_feature_enabled

        flag = _make_flag(status="on", allow_anonymous=True)
        p1, p2 = _patch_flag(flag, None)
        with p1, p2:
            assert is_feature_enabled(FEATURE, "anonymous") is True

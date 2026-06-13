"""Tests for the unified org-pooled run accounting (issue #814 stage 1).

Stage 1 ships ``treesight.billing.accounting`` with no callers — these
tests are the contract. Wiring into ``/api/upload/token`` and the
orchestrator lands in stage 2 (#815/#816/#818).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from treesight.billing.accounting import (
    AccountingError,
    ConcurrencyError,
    MemberCapExceededError,
    OrgNotFoundError,
    QuotaExhaustedError,
    Reservation,
    compute_pool_allowance,
    finalize_run,
    get_pool_status,
    reserve_run,
)

# ── Module-level patch targets ───────────────────────────────────────────

_READ_ETAG = "treesight.storage.cosmos.read_item_with_etag"
_REPLACE_ETAG = "treesight.storage.cosmos.replace_item_with_etag"
_GET_ORG = "treesight.security.orgs.get_org"
_GET_SUB = "treesight.security.billing.get_effective_subscription"


# ── Helpers ──────────────────────────────────────────────────────────────


def _org(
    *,
    org_id: str = "org-1",
    members: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    members_caps: dict[str, int] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": org_id,
        "org_id": org_id,
        "doc_type": "org",
        "members": members if members is not None else [{"user_id": "u-pro", "role": "owner"}],
    }
    if usage is not None:
        doc["usage"] = usage
    if members_caps is not None:
        doc["members_caps"] = members_caps
    return doc


def _sub(tier: str, status: str = "active") -> dict[str, Any]:
    return {"tier": tier, "status": status, "emulated": False}


def _make_sub_lookup(by_user: dict[str, dict[str, Any]]):
    """Return a side_effect for get_effective_subscription."""

    def _lookup(user_id: str) -> dict[str, Any]:
        return by_user.get(user_id, _sub("free"))

    return _lookup


def _stub_storage(
    org: dict[str, Any],
    *,
    etag: str = "etag-1",
    conflict_then_succeed: int = 0,
):
    """Patch read_item_with_etag and replace_item_with_etag.

    Returns a dict tracking call counts; ``conflict_then_succeed`` controls
    how many times ``replace_item_with_etag`` raises before succeeding.
    """
    from treesight.storage import cosmos as cosmos_mod

    state = {"replace_calls": 0, "read_calls": 0, "conflicts_left": conflict_then_succeed}

    def _read(_container: str, _item_id: str, _pk: str):
        state["read_calls"] += 1
        return dict(org), etag  # return a copy so the module mutates its own copy

    def _replace(_container: str, item: dict[str, Any], *, etag: str):
        del etag  # ETag conflicts are simulated via conflicts_left
        state["replace_calls"] += 1
        if state["conflicts_left"] > 0:
            state["conflicts_left"] -= 1
            raise cosmos_mod.EtagPreconditionFailedError("simulated conflict")
        # mutate the captured org so subsequent reads see the new state
        org.clear()
        org.update(item)
        return item

    return state, _read, _replace


def _stub_storage_live_etag(org: dict[str, Any], *, etag_version: int = 1):
    """Patch read/replace with real etag checks for parallel tests."""
    from treesight.storage import cosmos as cosmos_mod

    lock = threading.Lock()
    state = {"replace_calls": 0, "read_calls": 0}
    version = [etag_version]

    def _read(_container: str, _item_id: str, _pk: str):
        with lock:
            state["read_calls"] += 1
            return deepcopy(org), f"etag-{version[0]}"

    def _replace(_container: str, item: dict[str, Any], *, etag: str):
        with lock:
            state["replace_calls"] += 1
            expected = f"etag-{version[0]}"
            if etag != expected:
                raise cosmos_mod.EtagPreconditionFailedError("simulated conflict")
            org.clear()
            org.update(item)
            version[0] += 1
            return item

    return state, _read, _replace


# =========================================================================
# §1 — Pool allowance computation
# =========================================================================


class TestPoolAllowance:
    def test_sums_active_member_plans(self):
        """Pool = sum(member.plan.run_limit) for active members."""
        org = _org(
            members=[
                {"user_id": "u-pro", "role": "owner"},
                {"user_id": "u-free-1", "role": "member"},
                {"user_id": "u-free-2", "role": "member"},
            ]
        )
        with patch(
            _GET_SUB,
            side_effect=_make_sub_lookup(
                {
                    "u-pro": _sub("pro"),
                    "u-free-1": _sub("free"),
                    "u-free-2": _sub("free"),
                }
            ),
        ):
            assert compute_pool_allowance(org) == 50 + 5 + 5

    def test_inactive_paid_member_falls_back_to_free(self):
        """A member with status=inactive contributes only the free allowance."""
        org = _org(members=[{"user_id": "u-pro-cancelled", "role": "owner"}])
        with patch(
            _GET_SUB,
            side_effect=_make_sub_lookup(
                {
                    "u-pro-cancelled": _sub("pro", status="canceled"),
                }
            ),
        ):
            assert compute_pool_allowance(org) == 5

    def test_empty_org_has_zero_allowance(self):
        org = _org(members=[])
        with patch(_GET_SUB, return_value=_sub("free")):
            assert compute_pool_allowance(org) == 0


# =========================================================================
# §2 — reserve_run happy paths
# =========================================================================


class TestReserveRunHappyPath:
    def test_first_reservation_initialises_usage_block(self):
        org = _org(members=[{"user_id": "u-pro", "role": "owner"}])
        state, _read, _replace = _stub_storage(org)

        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            res = reserve_run(
                org_id="org-1",
                user_id="u-pro",
                parcel_count=10,
                is_eudr=True,
                instance_id="inst-1",
            )

        assert isinstance(res, Reservation)
        assert res.parcel_count == 10
        assert res.is_eudr is True
        assert res.pool_remaining == 40  # 50 - 10
        assert res.period_start.endswith("+00:00")
        assert state["replace_calls"] == 1

        # Persisted state
        assert org["usage"]["runs_reserved"] == 10
        assert "inst-1" in org["usage"]["reservations"]
        assert org["usage"]["reservations"]["inst-1"]["user_id"] == "u-pro"

    def test_pool_aggregates_across_members(self):
        """A 1-Pro + 2-Free org has a 60-parcel pool."""
        org = _org(
            members=[
                {"user_id": "u-pro", "role": "owner"},
                {"user_id": "u-free-1", "role": "member"},
                {"user_id": "u-free-2", "role": "member"},
            ]
        )
        _state, _read, _replace = _stub_storage(org)

        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(
                _GET_SUB,
                side_effect=_make_sub_lookup(
                    {
                        "u-pro": _sub("pro"),
                        "u-free-1": _sub("free"),
                        "u-free-2": _sub("free"),
                    }
                ),
            ),
        ):
            res = reserve_run(
                org_id="org-1",
                user_id="u-free-1",
                parcel_count=55,
                is_eudr=False,
                instance_id="inst-x",
            )
        assert res.pool_remaining == 5

    def test_idempotent_replay_returns_existing_reservation(self):
        """Calling reserve_run twice with the same instance_id is a no-op."""
        org = _org(members=[{"user_id": "u-pro", "role": "owner"}])
        _state, _read, _replace = _stub_storage(org)

        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            first = reserve_run(
                org_id="org-1",
                user_id="u-pro",
                parcel_count=7,
                is_eudr=False,
                instance_id="inst-dup",
            )
            second = reserve_run(
                org_id="org-1",
                user_id="u-pro",
                parcel_count=7,
                is_eudr=False,
                instance_id="inst-dup",
            )

        assert first.parcel_count == second.parcel_count == 7
        assert org["usage"]["runs_reserved"] == 7  # NOT 14
        assert _state["replace_calls"] == 1


# =========================================================================
# §3 — reserve_run rejections
# =========================================================================


class TestReserveRunRejections:
    def test_org_not_found_raises(self):
        with (
            patch(_READ_ETAG, return_value=None),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            with pytest.raises(OrgNotFoundError):
                reserve_run(
                    org_id="missing",
                    user_id="u",
                    parcel_count=1,
                    is_eudr=False,
                    instance_id="inst",
                )

    def test_quota_exhausted_when_pool_too_small(self):
        org = _org(members=[{"user_id": "u-free", "role": "owner"}])
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("free")),
        ):
            with pytest.raises(QuotaExhaustedError) as exc:
                reserve_run(
                    org_id="org-1",
                    user_id="u-free",
                    parcel_count=10,  # free pool is 5
                    is_eudr=False,
                    instance_id="inst",
                )
        assert exc.value.reason == "quota_exhausted"

    def test_member_cap_blocks_within_pool(self):
        """Per-member cap rejects even when org pool has room."""
        org = _org(
            members=[
                {"user_id": "u-pro", "role": "owner"},
                {"user_id": "u-junior", "role": "member"},
            ],
            members_caps={"u-junior": 5},
        )
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(
                _GET_SUB,
                side_effect=_make_sub_lookup(
                    {
                        "u-pro": _sub("pro"),
                        "u-junior": _sub("free"),
                    }
                ),
            ),
        ):
            with pytest.raises(MemberCapExceededError) as exc:
                reserve_run(
                    org_id="org-1",
                    user_id="u-junior",
                    parcel_count=6,  # pool has 50+5=55, but cap is 5
                    is_eudr=False,
                    instance_id="inst",
                )
        assert exc.value.reason == "member_cap_exceeded"

    def test_member_cap_unset_means_unlimited(self):
        org = _org(
            members=[{"user_id": "u-pro", "role": "owner"}],
            members_caps={},  # explicit empty map
        )
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            res = reserve_run(
                org_id="org-1",
                user_id="u-pro",
                parcel_count=50,
                is_eudr=False,
                instance_id="inst",
            )
        assert res.pool_remaining == 0

    def test_member_cap_holds_across_finalize(self):
        """Caps must bind across the period, not just in-flight runs.

        Regression for the loophole where ``finalize_run`` deletes the
        reservation, allowing a capped user to repeatedly reserve+finalize
        beyond their cap as long as the org pool has room.
        """
        org = _org(
            members=[
                {"user_id": "u-pro", "role": "owner"},
                {"user_id": "u-junior", "role": "member"},
            ],
            members_caps={"u-junior": 5},
        )
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(
                _GET_SUB,
                side_effect=_make_sub_lookup({"u-pro": _sub("pro"), "u-junior": _sub("free")}),
            ),
        ):
            reserve_run(
                org_id="org-1",
                user_id="u-junior",
                parcel_count=5,
                is_eudr=False,
                instance_id="inst-a",
            )
            finalize_run(org_id="org-1", instance_id="inst-a", status="completed")
            with pytest.raises(MemberCapExceededError):
                reserve_run(
                    org_id="org-1",
                    user_id="u-junior",
                    parcel_count=1,
                    is_eudr=False,
                    instance_id="inst-b",
                )

    def test_failed_run_refunds_member_cap(self):
        """Failed runs return budget to the per-user counter."""
        org = _org(
            members=[
                {"user_id": "u-pro", "role": "owner"},
                {"user_id": "u-junior", "role": "member"},
            ],
            members_caps={"u-junior": 5},
        )
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(
                _GET_SUB,
                side_effect=_make_sub_lookup({"u-pro": _sub("pro"), "u-junior": _sub("free")}),
            ),
        ):
            reserve_run(
                org_id="org-1",
                user_id="u-junior",
                parcel_count=5,
                is_eudr=False,
                instance_id="inst-a",
            )
            finalize_run(org_id="org-1", instance_id="inst-a", status="failed")
            # Cap should have been refunded — second reservation succeeds.
            res = reserve_run(
                org_id="org-1",
                user_id="u-junior",
                parcel_count=5,
                is_eudr=False,
                instance_id="inst-b",
            )
        assert res.parcel_count == 5

    def test_invalid_parcel_count_raises_value_error(self):
        with pytest.raises(ValueError):
            reserve_run(
                org_id="org-1",
                user_id="u",
                parcel_count=0,
                is_eudr=False,
                instance_id="inst",
            )

    def test_all_rejections_are_accounting_errors(self):
        """Sanity: callers can catch a single base type."""
        for cls in (
            OrgNotFoundError,
            QuotaExhaustedError,
            MemberCapExceededError,
            ConcurrencyError,
        ):
            assert issubclass(cls, AccountingError)


# =========================================================================
# §4 — Period rollover
# =========================================================================


class TestPeriodRollover:
    def test_stale_usage_archived_on_new_month(self):
        """When the existing usage block belongs to a previous period, archive it."""
        org = _org(
            members=[{"user_id": "u-pro", "role": "owner"}],
            usage={
                "period_start": "2020-01-01T00:00:00+00:00",
                "period_end": "2020-02-01T00:00:00+00:00",
                "runs_reserved": 0,
                "runs_completed": 49,
                "runs_refunded": 1,
                "reservations": {},
                "finalized_instance_ids": ["old-inst"],
            },
        )
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            reserve_run(
                org_id="org-1",
                user_id="u-pro",
                parcel_count=1,
                is_eudr=False,
                instance_id="inst-new",
            )

        assert org["usage"]["runs_reserved"] == 1
        assert org["usage"]["runs_completed"] == 0
        history = org["usage_history"]
        assert len(history) == 1
        assert history[0]["runs_completed"] == 49

    def test_history_is_capped_at_twelve(self):
        org = _org(
            members=[{"user_id": "u-pro", "role": "owner"}],
            usage={
                "period_start": "2020-01-01T00:00:00+00:00",
                "period_end": "2020-02-01T00:00:00+00:00",
                "runs_reserved": 0,
                "runs_completed": 0,
                "runs_refunded": 0,
                "reservations": {},
                "finalized_instance_ids": [],
            },
        )
        org["usage_history"] = [
            {"period_end": f"2020-{m:02d}-01T00:00:00+00:00"} for m in range(2, 14)
        ]
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            reserve_run(
                org_id="org-1",
                user_id="u-pro",
                parcel_count=1,
                is_eudr=False,
                instance_id="inst-new",
            )
        assert len(org["usage_history"]) == 12


# =========================================================================
# §5 — ETag concurrency
# =========================================================================


class TestEtagConcurrency:
    def test_one_conflict_then_succeeds(self):
        org = _org(members=[{"user_id": "u-pro", "role": "owner"}])
        state, _read, _replace = _stub_storage(org, conflict_then_succeed=1)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            res = reserve_run(
                org_id="org-1",
                user_id="u-pro",
                parcel_count=1,
                is_eudr=False,
                instance_id="inst",
            )
        assert res.parcel_count == 1
        assert state["read_calls"] == 2
        assert state["replace_calls"] == 2

    def test_persistent_conflict_raises_concurrency_error(self):
        org = _org(members=[{"user_id": "u-pro", "role": "owner"}])
        state, _read, _replace = _stub_storage(org, conflict_then_succeed=10)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            with pytest.raises(ConcurrencyError):
                reserve_run(
                    org_id="org-1",
                    user_id="u-pro",
                    parcel_count=1,
                    is_eudr=False,
                    instance_id="inst",
                )
        assert state["replace_calls"] == 5  # MAX_ETAG_RETRIES

    def test_parallel_reservations_cap_successes_at_allowance(self):
        org = _org(members=[{"user_id": "u-free", "role": "owner"}])
        _state, _read, _replace = _stub_storage_live_etag(org)
        attempts = 8

        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
            patch(_GET_SUB, return_value=_sub("free")),
        ):
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(
                        reserve_run,
                        org_id="org-1",
                        user_id="u-free",
                        parcel_count=1,
                        is_eudr=False,
                        instance_id=f"inst-{i}",
                    )
                    for i in range(attempts)
                ]

        successes = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except QuotaExhaustedError:
                pass

        assert successes == 5
        assert org["usage"]["runs_reserved"] == 5


# =========================================================================
# §6 — finalize_run
# =========================================================================


class TestFinalizeRun:
    def _seed(self):
        """Return an org doc with one in-flight reservation."""
        return _org(
            members=[{"user_id": "u-pro", "role": "owner"}],
            usage={
                "period_start": "2026-05-01T00:00:00+00:00",
                "period_end": "2026-06-01T00:00:00+00:00",
                "runs_reserved": 7,
                "runs_completed": 0,
                "runs_refunded": 0,
                "reservations": {
                    "inst-1": {
                        "user_id": "u-pro",
                        "parcel_count": 7,
                        "is_eudr": True,
                        "ts": "2026-05-14T10:00:00+00:00",
                    }
                },
                "finalized_instance_ids": [],
                "member_used": {"u-pro": 7},
            },
        )

    def test_completed_moves_reserved_to_completed(self):
        org = self._seed()
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
        ):
            finalize_run(org_id="org-1", instance_id="inst-1", status="completed")
        u = org["usage"]
        assert u["runs_reserved"] == 0
        assert u["runs_completed"] == 7
        assert u["runs_refunded"] == 0
        assert "inst-1" not in u["reservations"]
        assert "inst-1" in u["finalized_instance_ids"]

    def test_failed_moves_reserved_to_refunded(self):
        org = self._seed()
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
        ):
            finalize_run(org_id="org-1", instance_id="inst-1", status="failed")
        u = org["usage"]
        assert u["runs_reserved"] == 0
        assert u["runs_completed"] == 0
        assert u["runs_refunded"] == 7
        # Failed runs refund the per-member counter so they don't burn caps.
        assert u["member_used"]["u-pro"] == 0

    def test_completed_keeps_member_counter(self):
        """Successful runs must NOT refund the per-user counter.

        Otherwise per-member caps could be bypassed by submitting in batches.
        """
        org = self._seed()
        _state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
        ):
            finalize_run(org_id="org-1", instance_id="inst-1", status="completed")
        assert org["usage"]["member_used"]["u-pro"] == 7

    def test_idempotent_replay_is_noop(self):
        org = self._seed()
        state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
        ):
            finalize_run(org_id="org-1", instance_id="inst-1", status="completed")
            finalize_run(org_id="org-1", instance_id="inst-1", status="completed")

        assert org["usage"]["runs_completed"] == 7  # NOT 14
        assert state["replace_calls"] == 1

    def test_unknown_reservation_is_noop(self):
        org = self._seed()
        state, _read, _replace = _stub_storage(org)
        with (
            patch(_READ_ETAG, side_effect=_read),
            patch(_REPLACE_ETAG, side_effect=_replace),
        ):
            finalize_run(org_id="org-1", instance_id="ghost", status="completed")
        assert state["replace_calls"] == 0
        assert org["usage"]["runs_reserved"] == 7

    def test_missing_org_is_noop(self):
        with patch(_READ_ETAG, return_value=None):
            finalize_run(org_id="ghost", instance_id="inst-1", status="completed")

    def test_invalid_status_raises_value_error(self):
        with pytest.raises(ValueError):
            finalize_run(org_id="org-1", instance_id="inst-1", status="weird")  # type: ignore[arg-type]


# =========================================================================
# §7 — get_pool_status
# =========================================================================


class TestGetPoolStatus:
    def test_returns_snapshot_with_per_member_breakdown(self):
        org = _org(
            members=[
                {"user_id": "u-pro", "role": "owner"},
                {"user_id": "u-free", "role": "member"},
            ],
            members_caps={"u-free": 3},
        )
        # Inject a current-period usage block.
        from treesight.billing.accounting import _current_period_bounds

        ps, pe = _current_period_bounds(datetime.now(UTC))
        org["usage"] = {
            "period_start": ps,
            "period_end": pe,
            "runs_reserved": 4,
            "runs_completed": 2,
            "runs_refunded": 0,
            "reservations": {
                "i-1": {"user_id": "u-pro", "parcel_count": 3, "is_eudr": True, "ts": ps},
                "i-2": {"user_id": "u-free", "parcel_count": 1, "is_eudr": False, "ts": ps},
            },
            "finalized_instance_ids": [],
            "member_used": {"u-pro": 5, "u-free": 1},  # u-pro has 3 in-flight + 2 completed
        }
        with (
            patch(_GET_ORG, return_value=org),
            patch(
                _GET_SUB,
                side_effect=_make_sub_lookup(
                    {
                        "u-pro": _sub("pro"),
                        "u-free": _sub("free"),
                    }
                ),
            ),
        ):
            snap = get_pool_status("org-1")

        assert snap["allowance"] == 55  # 50 + 5
        assert snap["reserved"] == 4
        assert snap["completed"] == 2
        assert snap["available"] == 49
        # u-pro is 5 (3 in-flight + 2 completed); u-free is 1.
        assert snap["per_member"]["u-pro"] == {"allowance": 50, "used": 5, "cap": None}
        assert snap["per_member"]["u-free"] == {"allowance": 5, "used": 1, "cap": 3}

    def test_org_not_found_raises(self):
        with patch(_GET_ORG, return_value=None):
            with pytest.raises(OrgNotFoundError):
                get_pool_status("missing")

    def test_stale_usage_block_reports_zero(self):
        org = _org(
            members=[{"user_id": "u-pro", "role": "owner"}],
            usage={
                "period_start": "2020-01-01T00:00:00+00:00",
                "period_end": "2020-02-01T00:00:00+00:00",
                "runs_reserved": 9,
                "runs_completed": 9,
                "runs_refunded": 0,
                "reservations": {},
                "finalized_instance_ids": [],
            },
        )
        with (
            patch(_GET_ORG, return_value=org),
            patch(_GET_SUB, return_value=_sub("pro")),
        ):
            snap = get_pool_status("org-1")
        assert snap["reserved"] == 0
        assert snap["completed"] == 0
        assert snap["available"] == 50

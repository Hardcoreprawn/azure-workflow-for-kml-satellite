"""Tests for concurrency cap helpers (treesight/pipeline/concurrency.py — #759)
and SAFE_MODE activity guard (#759).
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

import azure.functions as func

from tests.conftest import TEST_LOCAL_ORIGIN, make_test_request


def _make_submit_req(body=None):
    return make_test_request(
        url="/api/analysis/submit",
        method="POST",
        body=body or {"kml_content": "<kml></kml>"},
        origin=TEST_LOCAL_ORIGIN,
        auth_header="Bearer fake-token",
    )


# ---------------------------------------------------------------------------
# Unit tests for count_active_runs and at_concurrency_cap
# ---------------------------------------------------------------------------


class TestCountActiveRuns:
    def test_default_container_name_matches_runs_constant(self):
        """Regression: default container must be COSMOS_CONTAINER_RUNS, not 'run-records'."""
        import inspect

        from treesight.constants import COSMOS_CONTAINER_RUNS
        from treesight.pipeline.concurrency import (
            at_concurrency_cap,
            count_active_runs,
            release_admission_slot,
            reserve_admission_slot,
        )

        sig_count = inspect.signature(count_active_runs)
        assert sig_count.parameters["container_name"].default == COSMOS_CONTAINER_RUNS

        sig_cap = inspect.signature(at_concurrency_cap)
        assert sig_cap.parameters["container_name"].default == COSMOS_CONTAINER_RUNS

        sig_reserve = inspect.signature(reserve_admission_slot)
        assert sig_reserve.parameters["container_name"].default == COSMOS_CONTAINER_RUNS

        sig_release = inspect.signature(release_admission_slot)
        assert sig_release.parameters["container_name"].default == COSMOS_CONTAINER_RUNS

    def test_default_call_reads_admission_state_from_runs_container(self):
        """Regression: calling with no args must read admission state from 'runs'."""
        from treesight.constants import COSMOS_CONTAINER_RUNS
        from treesight.pipeline.concurrency import count_active_runs

        captured: list[str] = []

        def _fake_read_item_with_etag(container_name, item_id, partition_key):
            captured.append(container_name)
            return ({"id": item_id, "user_id": partition_key, "active_slots": {}}, "etag-1")

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", side_effect=_fake_read_item_with_etag),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 15),
        ):
            count_active_runs()

        assert captured == [COSMOS_CONTAINER_RUNS]

    def test_returns_zero_when_cosmos_unavailable(self):
        from treesight.pipeline.concurrency import count_active_runs

        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            assert count_active_runs() == 0

    def test_returns_count_from_admission_slots(self):
        from treesight.pipeline.concurrency import count_active_runs

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch(
                "treesight.storage.cosmos.read_item_with_etag",
                return_value=(
                    {"id": "x", "user_id": "__system__", "active_slots": {"a": "2026-01-01T00:00:00+00:00"}},
                    "e1",
                ),
            ),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 10_000_000),
        ):
            result = count_active_runs()
        assert result == 1

    def test_returns_zero_on_cosmos_exception(self):
        from treesight.pipeline.concurrency import count_active_runs

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", side_effect=RuntimeError("Cosmos down")),
        ):
            result = count_active_runs()
        assert result == 0

    def test_returns_zero_when_admission_doc_missing(self):
        from treesight.pipeline.concurrency import count_active_runs

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", return_value=None),
        ):
            result = count_active_runs()
        assert result == 0

    def test_reconciles_stale_slots_during_count(self):
        from treesight.pipeline.concurrency import count_active_runs

        stale = "2000-01-01T00:00:00+00:00"
        fresh = "2100-01-01T00:00:00+00:00"
        doc = {"id": "x", "user_id": "__system__", "active_slots": {"stale": stale, "fresh": fresh}}
        replace_calls = []

        def _replace(_container_name, item, *, etag):
            replace_calls.append((deepcopy(item), etag))
            return item

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", return_value=(doc, "e1")),
            patch("treesight.storage.cosmos.replace_item_with_etag", side_effect=_replace),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 60),
        ):
            assert count_active_runs() == 1

        assert len(replace_calls) == 1
        assert "stale" not in replace_calls[0][0]["active_slots"]


class TestAdmissionReservation:
    def test_reserve_returns_true_when_cosmos_unavailable(self):
        from treesight.pipeline.concurrency import reserve_admission_slot

        with (
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.storage.cosmos.cosmos_available", return_value=False),
        ):
            assert reserve_admission_slot("inst-1") is True

    def test_reserve_denies_when_cap_reached(self):
        from treesight.pipeline.concurrency import reserve_admission_slot

        doc = {
            "id": "x",
            "user_id": "__system__",
            "active_slots": {"a": "2100-01-01T00:00:00+00:00", "b": "2100-01-01T00:00:00+00:00"},
        }

        with (
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 60),
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", return_value=(doc, "e1")),
        ):
            assert reserve_admission_slot("inst-new") is False

    def test_reserve_is_idempotent_for_same_instance(self):
        from treesight.pipeline.concurrency import reserve_admission_slot

        doc = {"id": "x", "user_id": "__system__", "active_slots": {"inst-1": "2100-01-01T00:00:00+00:00"}}
        with (
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 60),
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", return_value=(doc, "e1")),
            patch("treesight.storage.cosmos.replace_item_with_etag") as replace_mock,
        ):
            assert reserve_admission_slot("inst-1") is True
        replace_mock.assert_not_called()

    def test_reserve_fails_closed_on_cosmos_error(self):
        from treesight.pipeline.concurrency import AdmissionUnavailableError, reserve_admission_slot

        with (
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", side_effect=RuntimeError("boom")),
        ):
            try:
                reserve_admission_slot("inst-1")
            except AdmissionUnavailableError:
                pass
            else:
                raise AssertionError("Expected AdmissionUnavailableError")

    def test_contention_allows_only_one_at_cap_one(self):
        from treesight.pipeline.concurrency import reserve_admission_slot
        from treesight.storage.cosmos import EtagPreconditionFailedError

        store = {"etag": "1", "doc": {"id": "x", "user_id": "__system__", "active_slots": {}}}

        def _read(_container_name, _item_id, _partition_key):
            return deepcopy(store["doc"]), store["etag"]

        def _replace(_container_name, item, *, etag):
            if etag != store["etag"]:
                raise EtagPreconditionFailedError("conflict")
            store["doc"] = deepcopy(item)
            store["etag"] = str(int(store["etag"]) + 1)
            return item

        with (
            patch("treesight.config.MAX_CONCURRENT_JOBS", 1),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 60),
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", side_effect=_read),
            patch("treesight.storage.cosmos.replace_item_with_etag", side_effect=_replace),
            patch("treesight.storage.cosmos.upsert_item", return_value={}),
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(reserve_admission_slot, ["inst-a", "inst-b"]))

        assert outcomes.count(True) == 1
        assert outcomes.count(False) == 1


class TestAdmissionRelease:
    def test_release_unknown_slot_is_noop(self):
        from treesight.pipeline.concurrency import release_admission_slot

        doc = {"id": "x", "user_id": "__system__", "active_slots": {"inst-1": "2100-01-01T00:00:00+00:00"}}
        with (
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 60),
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", return_value=(doc, "e1")),
            patch("treesight.storage.cosmos.replace_item_with_etag") as replace_mock,
        ):
            assert release_admission_slot("missing") is False
        replace_mock.assert_not_called()

    def test_release_removes_slot(self):
        from treesight.pipeline.concurrency import release_admission_slot

        doc = {"id": "x", "user_id": "__system__", "active_slots": {"inst-1": "2100-01-01T00:00:00+00:00"}}
        replace_calls = []

        def _replace(_container_name, item, *, etag):
            replace_calls.append((deepcopy(item), etag))
            return item

        with (
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 60),
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.read_item_with_etag", return_value=(doc, "e1")),
            patch("treesight.storage.cosmos.replace_item_with_etag", side_effect=_replace),
        ):
            assert release_admission_slot("inst-1") is True

        assert replace_calls[0][0]["active_slots"] == {}


class TestAtConcurrencyCap:
    def test_returns_false_below_cap(self):
        from treesight.pipeline.concurrency import at_concurrency_cap

        with (
            patch("treesight.pipeline.concurrency.count_active_runs", return_value=1),
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
        ):
            assert at_concurrency_cap() is False

    def test_returns_true_at_cap(self):
        from treesight.pipeline.concurrency import at_concurrency_cap

        with (
            patch("treesight.pipeline.concurrency.count_active_runs", return_value=2),
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
        ):
            assert at_concurrency_cap() is True

    def test_returns_false_when_cap_is_zero(self):
        """cap=0 disables the guard entirely."""
        from treesight.pipeline.concurrency import at_concurrency_cap

        with patch("treesight.config.MAX_CONCURRENT_JOBS", 0):
            assert at_concurrency_cap() is False


# ---------------------------------------------------------------------------
# Integration-style test: submission endpoint returns 429 at cap
# ---------------------------------------------------------------------------


class TestSubmissionConcurrencyCap:
    def test_submit_at_cap_returns_429(self):
        """Submission returns 429 with Retry-After when concurrency cap is reached."""
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_submit_req()

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.reserve_admission_slot", return_value=False),
        ):
            resp = asyncio.run(_submit_analysis_request(req))

        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "30"
        body = json.loads(resp.get_body())
        assert "cap" in body.get("error", "").lower()

    def test_submit_below_cap_proceeds(self):
        """Submission is not blocked when below the cap."""
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_submit_req()

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.reserve_admission_slot", return_value=True),
            patch("blueprints.pipeline.submission.get_user_org", return_value={"org_id": "org-123"}),
            patch("blueprints.pipeline.submission.reserve_run", return_value={"reserved_parcels": 1}),
            patch("treesight.storage.client.BlobStorageClient"),
        ):
            resp = asyncio.run(_submit_analysis_request(req))

        assert resp.status_code == 202

    def test_submit_returns_503_when_admission_unavailable(self):
        from blueprints.pipeline.submission import _submit_analysis_request
        from treesight.pipeline.concurrency import AdmissionUnavailableError

        req = _make_submit_req()

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch(
                "blueprints.pipeline.submission.reserve_admission_slot",
                side_effect=AdmissionUnavailableError("cosmos unavailable"),
            ),
        ):
            resp = asyncio.run(_submit_analysis_request(req))

        assert resp.status_code == 503

    def test_quota_rejection_releases_admission_slot(self):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = _make_submit_req()
        quota_resp = func.HttpResponse(
            json.dumps({"error": "quota"}),
            status_code=403,
            mimetype="application/json",
        )

        with (
            patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123")),
            patch("blueprints.pipeline.submission.reserve_admission_slot", return_value=True),
            patch("blueprints.pipeline.submission._resolve_quota", return_value=(False, "", quota_resp)),
            patch("blueprints.pipeline.submission.release_admission_slot") as release_mock,
        ):
            resp = asyncio.run(_submit_analysis_request(req))

        assert resp.status_code == 403
        release_mock.assert_called_once()


# ---------------------------------------------------------------------------
# SAFE_MODE tests — activity guard (#759)
# ---------------------------------------------------------------------------


class TestSafeMode:
    def test_enrich_skipped_when_safe_mode_on(self):
        """enrich_data_sources returns early with safe_mode payload when SAFE_MODE=True."""
        from blueprints.pipeline.activities import enrich_data_sources

        with patch("treesight.config.SAFE_MODE", True):
            result = enrich_data_sources({"instance_id": "test-id", "user_id": "u1"})

        assert result["safe_mode"] is True
        assert "skipped" in result
        assert "weather" in result["skipped"]

    def test_enrich_not_skipped_when_safe_mode_off(self):
        """enrich_data_sources runs normally when SAFE_MODE=False."""
        from blueprints.pipeline.activities import enrich_data_sources

        with (
            patch("treesight.config.SAFE_MODE", False),
            patch(
                "treesight.pipeline.enrichment.enrich_data_sources",
                return_value={"enriched": True},
            ),
        ):
            result = enrich_data_sources(
                {
                    "instance_id": "test-id",
                    "user_id": "u1",
                    "coords": [],
                    "eudr_mode": False,
                }
            )

        assert result == {"enriched": True}
        assert "safe_mode" not in result

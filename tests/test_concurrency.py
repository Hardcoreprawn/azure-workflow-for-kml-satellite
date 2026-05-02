"""Tests for concurrency cap helpers (treesight/pipeline/concurrency.py — #759)
and SAFE_MODE activity guard (#759).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

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
    def test_returns_zero_when_cosmos_unavailable(self):
        from treesight.pipeline.concurrency import count_active_runs

        with patch("treesight.storage.cosmos.cosmos_available", return_value=False):
            assert count_active_runs() == 0

    def test_returns_count_from_cosmos(self):
        from treesight.pipeline.concurrency import count_active_runs

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", return_value=[3]),
        ):
            result = count_active_runs()
        assert result == 3

    def test_returns_zero_on_cosmos_exception(self):
        from treesight.pipeline.concurrency import count_active_runs

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", side_effect=RuntimeError("Cosmos down")),
        ):
            result = count_active_runs()
        assert result == 0

    def test_returns_zero_when_query_empty(self):
        from treesight.pipeline.concurrency import count_active_runs

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", return_value=[]),
        ):
            result = count_active_runs()
        assert result == 0


class TestAtConcurrencyCap:
    def test_returns_false_below_cap(self):
        from treesight.pipeline.concurrency import at_concurrency_cap

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", return_value=[1]),
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 15),
        ):
            assert at_concurrency_cap() is False

    def test_returns_true_at_cap(self):
        from treesight.pipeline.concurrency import at_concurrency_cap

        with (
            patch("treesight.storage.cosmos.cosmos_available", return_value=True),
            patch("treesight.storage.cosmos.query_items", return_value=[2]),
            patch("treesight.config.MAX_CONCURRENT_JOBS", 2),
            patch("treesight.config.MAX_JOB_DURATION_MINUTES", 15),
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
            patch("blueprints.pipeline.submission.at_concurrency_cap", return_value=True),
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
            patch("blueprints.pipeline.submission.at_concurrency_cap", return_value=False),
            patch("blueprints.pipeline.submission.consume_quota", return_value=5),
            patch("treesight.storage.client.BlobStorageClient"),
        ):
            resp = asyncio.run(_submit_analysis_request(req))

        assert resp.status_code == 202


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

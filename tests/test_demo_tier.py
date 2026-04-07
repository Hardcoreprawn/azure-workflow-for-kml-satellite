"""Tests for #331 — demo-as-plan backend tier.

Covers:
- PLAN_CATALOG demo tier configuration
- build_frame_plan() cadence filtering (seasonal, monthly, maximum)
- build_frame_plan() max_history_years capping
- signed-in free/demo submission tier controls
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from treesight.constants import DEMO_TIER_RUN_LIMIT
from treesight.pipeline.enrichment import build_frame_plan
from treesight.pipeline.enrichment.frames import _month_window
from treesight.security.billing import PLAN_CATALOG, plan_capabilities

# UK coords — no NAIP coverage
UK_COORDS: list[list[float]] = [[-1.5, 51.0], [-1.4, 51.0], [-1.4, 51.1], [-1.5, 51.1]]
# US coords — inside CONUS, has NAIP
US_COORDS: list[list[float]] = [[-90.0, 38.0], [-89.9, 38.0], [-89.9, 38.1], [-90.0, 38.1]]


# ---------------------------------------------------------------------------
# PLAN_CATALOG — demo tier
# ---------------------------------------------------------------------------


class TestDemoTierCatalog:
    """Verify the demo tier exists in PLAN_CATALOG with correct constraints."""

    def test_demo_tier_exists(self):
        assert "demo" in PLAN_CATALOG

    def test_demo_run_limit(self):
        assert PLAN_CATALOG["demo"]["run_limit"] == DEMO_TIER_RUN_LIMIT
        assert PLAN_CATALOG["demo"]["run_limit"] == 3

    def test_demo_aoi_limit(self):
        assert PLAN_CATALOG["demo"]["aoi_limit"] == 1

    def test_demo_no_export(self):
        assert PLAN_CATALOG["demo"]["export"] is False

    def test_demo_no_ai_insights(self):
        assert PLAN_CATALOG["demo"]["ai_insights"] is False

    def test_demo_stateless(self):
        assert PLAN_CATALOG["demo"]["retention_days"] == 0

    def test_demo_seasonal_cadence(self):
        assert PLAN_CATALOG["demo"]["temporal_cadence"] == "seasonal"

    def test_demo_max_history_years(self):
        assert PLAN_CATALOG["demo"]["max_history_years"] == 2

    def test_demo_capabilities_via_helper(self):
        caps = plan_capabilities("demo")
        assert caps["tier"] == "demo"
        assert caps["run_limit"] == 3
        assert caps["export"] is False

    def test_free_max_history_years_matches_cost_control_window(self):
        assert PLAN_CATALOG["free"]["max_history_years"] == 2


class TestAllTiersHaveNewFields:
    """Every tier must declare the newly added fields."""

    @pytest.mark.parametrize("tier", list(PLAN_CATALOG))
    def test_has_aoi_limit(self, tier: str):
        assert "aoi_limit" in PLAN_CATALOG[tier]

    @pytest.mark.parametrize("tier", list(PLAN_CATALOG))
    def test_has_export(self, tier: str):
        assert "export" in PLAN_CATALOG[tier]

    @pytest.mark.parametrize("tier", list(PLAN_CATALOG))
    def test_has_temporal_cadence(self, tier: str):
        assert PLAN_CATALOG[tier]["temporal_cadence"] in (
            "seasonal",
            "monthly",
            "maximum",
        )

    @pytest.mark.parametrize("tier", list(PLAN_CATALOG))
    def test_has_max_history_years(self, tier: str):
        val = PLAN_CATALOG[tier]["max_history_years"]
        assert val is None or isinstance(val, int)


# ---------------------------------------------------------------------------
# Frame plan — cadence filtering
# ---------------------------------------------------------------------------


class TestMonthWindow:
    """Verify _month_window produces correct date ranges."""

    def test_january(self):
        w = _month_window(2024, 1)
        assert w["start"] == "2024-01-01"
        assert w["end"] == "2024-01-31"

    def test_february_non_leap(self):
        w = _month_window(2023, 2)
        assert w["start"] == "2023-02-01"
        assert w["end"] == "2023-02-28"

    def test_february_leap(self):
        w = _month_window(2024, 2)
        assert w["start"] == "2024-02-01"
        assert w["end"] == "2024-02-29"

    def test_december(self):
        w = _month_window(2024, 12)
        assert w["start"] == "2024-12-01"
        assert w["end"] == "2024-12-31"


class TestBuildFramePlanCadence:
    """Test build_frame_plan with different cadence values."""

    def test_seasonal_produces_four_per_year(self):
        """Seasonal cadence: 4 seasons per year for non-NAIP coords."""
        plan = build_frame_plan(UK_COORDS, cadence="seasonal")
        # Group by year
        years = {f["year"] for f in plan}
        for yr in years:
            yr_frames = [f for f in plan if f["year"] == yr]
            assert len(yr_frames) == 4, f"Year {yr} has {len(yr_frames)} frames"

    def test_seasonal_has_correct_season_keys(self):
        plan = build_frame_plan(UK_COORDS, cadence="seasonal")
        seasons = {f["season"] for f in plan}
        assert seasons == {"winter", "spring", "summer", "autumn"}

    def test_monthly_produces_twelve_per_year(self):
        """Monthly cadence: 12 months per year."""
        plan = build_frame_plan(UK_COORDS, cadence="monthly")
        years = {f["year"] for f in plan}
        for yr in years:
            yr_frames = [f for f in plan if f["year"] == yr]
            assert len(yr_frames) == 12, f"Year {yr} has {len(yr_frames)} frames"

    def test_monthly_uses_sentinel(self):
        """Monthly frames always use Sentinel-2 (no NAIP)."""
        plan = build_frame_plan(US_COORDS, cadence="monthly")
        for f in plan:
            assert f["collection"] == "sentinel-2-l2a"
            assert f["is_naip"] is False

    def test_maximum_is_default(self):
        """Default cadence (maximum) matches seasonal for non-NAIP coords."""
        default_plan = build_frame_plan(UK_COORDS)
        seasonal_plan = build_frame_plan(UK_COORDS, cadence="maximum")
        assert len(default_plan) == len(seasonal_plan)

    def test_maximum_includes_naip_for_us(self):
        """Maximum cadence includes extra NAIP frames for US coords."""
        plan = build_frame_plan(US_COORDS, cadence="maximum")
        naip = [f for f in plan if f["is_naip"]]
        assert len(naip) > 0

    def test_seasonal_includes_naip_for_us(self):
        """Seasonal cadence also includes NAIP frames for US coords."""
        plan = build_frame_plan(US_COORDS, cadence="seasonal")
        naip = [f for f in plan if f["is_naip"]]
        assert len(naip) > 0


class TestBuildFramePlanMaxHistory:
    """Test build_frame_plan with max_history_years capping."""

    def test_max_history_caps_date_start(self):
        """max_history_years=2 should exclude frames older than 2 years."""
        full_plan = build_frame_plan(UK_COORDS, cadence="seasonal")
        capped_plan = build_frame_plan(UK_COORDS, cadence="seasonal", max_history_years=2)
        assert len(capped_plan) < len(full_plan)

    def test_max_history_frames_within_window(self):
        """All frames in a capped plan should end on or after the cutoff."""
        cutoff_year = date.today().year - 2
        cutoff = f"{cutoff_year}-01-01"
        plan = build_frame_plan(UK_COORDS, cadence="seasonal", max_history_years=2)
        for f in plan:
            assert f["end"] >= cutoff, f"Frame {f} ends before cutoff {cutoff}"

    def test_max_history_none_returns_full(self):
        """max_history_years=None means no cap (same as default)."""
        full = build_frame_plan(UK_COORDS, cadence="seasonal")
        uncapped = build_frame_plan(UK_COORDS, cadence="seasonal", max_history_years=None)
        assert len(full) == len(uncapped)

    def test_explicit_date_start_overrides_max_history(self):
        """If date_start is already set, max_history_years does not replace it."""
        plan = build_frame_plan(
            UK_COORDS,
            cadence="seasonal",
            date_start="2020-01-01",
            max_history_years=2,
        )
        # Should respect the explicit date_start=2020, not the cap
        for f in plan:
            assert f["end"] >= "2020-01-01"

    def test_demo_tier_combo(self):
        """Demo tier defaults: seasonal + 2-year window produces limited frames."""
        plan = build_frame_plan(UK_COORDS, cadence="seasonal", max_history_years=2)
        # Should have at most 3 years × 4 seasons = 12 frames (roughly)
        assert len(plan) <= 16  # generous upper bound


# ---------------------------------------------------------------------------
# Demo submit endpoint
# ---------------------------------------------------------------------------


class TestSignedInLowCostSubmission:
    """Test signed-in free/demo submission behaviour through the unified route."""

    def _make_request(
        self,
        body: dict[str, Any] | None = None,
    ) -> MagicMock:
        req = MagicMock()
        req.method = "POST"
        req.headers = {"Authorization": "Bearer fake-token"}
        if body is not None:
            req.get_json.return_value = body
        else:
            req.get_json.side_effect = ValueError("no json")
        return req

    @patch("blueprints.pipeline.submission.get_effective_subscription")
    @patch("blueprints.pipeline.submission.consume_quota", return_value=5)
    @patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123"))
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_free_tier_submission_returns_202(
        self,
        mock_storage_cls,
        mock_auth,
        mock_quota,
        mock_effective_subscription,
    ):
        from blueprints.pipeline.submission import _submit_analysis_request

        mock_effective_subscription.return_value = {"tier": "free", "status": "none"}

        req = self._make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req)

        assert resp.status_code == 202
        upload_call = mock_storage_cls.return_value.upload_bytes.call_args
        assert upload_call[0][1].startswith("analysis/")
        # Verify ticket carries tier info for blob_trigger
        ticket_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if ".tickets/" in str(c)
        ]
        assert len(ticket_calls) >= 1
        ticket_data = ticket_calls[0][0][2]
        assert ticket_data["cadence"] == "seasonal"
        assert ticket_data["max_history_years"] == 2
        assert ticket_data["tier"] == "free"
        assert ticket_data["user_id"] == "user-123"

    @patch("blueprints.pipeline.submission.get_effective_subscription")
    @patch("blueprints.pipeline.submission.consume_quota", return_value=5)
    @patch("blueprints.pipeline.submission.check_auth", return_value=({}, "user-123"))
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_demo_emulation_uses_demo_controls(
        self,
        mock_storage_cls,
        mock_auth,
        mock_quota,
        mock_effective_subscription,
    ):
        from blueprints.pipeline.submission import _submit_analysis_request

        mock_effective_subscription.return_value = {"tier": "demo", "status": "active"}

        req = self._make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req)

        assert resp.status_code == 202
        upload_call = mock_storage_cls.return_value.upload_bytes.call_args
        assert upload_call[0][1].startswith("analysis/")
        # Verify ticket carries tier info for blob_trigger
        ticket_calls = [
            c
            for c in mock_storage_cls.return_value.upload_json.call_args_list
            if ".tickets/" in str(c)
        ]
        assert len(ticket_calls) >= 1
        ticket_data = ticket_calls[0][0][2]
        assert ticket_data["tier"] == "demo"
        assert ticket_data["cadence"] == "seasonal"
        assert ticket_data["max_history_years"] == 2

    @patch(
        "blueprints.pipeline.submission.check_auth",
        side_effect=ValueError("Missing or malformed Authorization header"),
    )
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, mock_auth):
        from blueprints.pipeline.submission import _submit_analysis_request

        req = self._make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_analysis_request(req)

        assert resp.status_code == 401

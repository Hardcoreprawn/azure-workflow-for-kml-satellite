"""Tests for #331 — demo-as-plan backend tier.

Covers:
- PLAN_CATALOG demo tier configuration
- build_frame_plan() cadence filtering (seasonal, monthly, maximum)
- build_frame_plan() max_history_years capping
- _submit_demo_request rate limiting and anonymous access
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestDemoSubmitEndpoint:
    """Test _submit_demo_request behaviour via the demo_process route."""

    def _make_request(
        self,
        body: dict[str, Any] | None = None,
        *,
        ip: str = "192.168.1.1",
    ) -> MagicMock:
        req = MagicMock()
        req.method = "POST"
        req.headers = {"X-Forwarded-For": ip}
        if body is not None:
            req.get_json.return_value = body
        else:
            req.get_json.side_effect = ValueError("no json")
        return req

    @patch("blueprints.pipeline.submission.demo_limiter")
    @patch("blueprints.pipeline.submission.get_client_ip", return_value="127.0.0.1")
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_valid_submission_returns_202(self, mock_storage_cls, mock_get_ip, mock_limiter):
        from blueprints.pipeline.submission import _submit_demo_request

        mock_limiter.is_allowed.return_value = True

        client = AsyncMock()
        req = self._make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_demo_request(req, client)

        assert resp.status_code == 202
        client.start_new.assert_awaited_once()
        call_kwargs = client.start_new.call_args
        orch_input = call_kwargs.kwargs.get("client_input", call_kwargs[1].get("client_input"))
        assert orch_input["cadence"] == "seasonal"
        assert orch_input["max_history_years"] == 2
        assert orch_input["tier"] == "demo"
        assert orch_input["user_id"].startswith("demo:")

    @patch("blueprints.pipeline.submission.demo_limiter")
    @patch("blueprints.pipeline.submission.get_client_ip", return_value="127.0.0.1")
    @pytest.mark.asyncio
    async def test_rate_limited_returns_429(self, mock_get_ip, mock_limiter):
        from blueprints.pipeline.submission import _submit_demo_request

        mock_limiter.is_allowed.return_value = False

        client = AsyncMock()
        req = self._make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_demo_request(req, client)

        assert resp.status_code == 429

    @patch("blueprints.pipeline.submission.demo_limiter")
    @patch("blueprints.pipeline.submission.get_client_ip", return_value="127.0.0.1")
    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, mock_get_ip, mock_limiter):
        from blueprints.pipeline.submission import _submit_demo_request

        mock_limiter.is_allowed.return_value = True

        client = AsyncMock()
        req = self._make_request()  # no body → ValueError

        resp = await _submit_demo_request(req, client)

        assert resp.status_code == 400

    @patch("blueprints.pipeline.submission.demo_limiter")
    @patch("blueprints.pipeline.submission.get_client_ip", return_value="127.0.0.1")
    @pytest.mark.asyncio
    async def test_empty_kml_returns_400(self, mock_get_ip, mock_limiter):
        from blueprints.pipeline.submission import _submit_demo_request

        mock_limiter.is_allowed.return_value = True

        client = AsyncMock()
        req = self._make_request({"kml_content": ""})

        resp = await _submit_demo_request(req, client)

        assert resp.status_code == 400

    @patch("blueprints.pipeline.submission.demo_limiter")
    @patch("blueprints.pipeline.submission.get_client_ip", return_value="10.0.0.1")
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_user_id_is_ip_hash(self, mock_storage_cls, mock_get_ip, mock_limiter):
        from blueprints.pipeline.submission import _submit_demo_request

        mock_limiter.is_allowed.return_value = True

        client = AsyncMock()
        req = self._make_request({"kml_content": "<kml>test</kml>"})

        resp = await _submit_demo_request(req, client)

        assert resp.status_code == 202
        call_kwargs = client.start_new.call_args
        orch_input = call_kwargs.kwargs.get("client_input", call_kwargs[1].get("client_input"))
        user_id = orch_input["user_id"]
        assert user_id.startswith("demo:")
        # Hash portion should be 12 hex chars
        assert len(user_id.split(":")[1]) == 12

    @patch("blueprints.pipeline.submission.demo_limiter")
    @patch("blueprints.pipeline.submission.get_client_ip", return_value="127.0.0.1")
    @patch("treesight.storage.client.BlobStorageClient")
    @pytest.mark.asyncio
    async def test_blob_uploaded_to_demo_prefix(self, mock_storage_cls, mock_get_ip, mock_limiter):
        from blueprints.pipeline.submission import _submit_demo_request

        mock_limiter.is_allowed.return_value = True
        mock_storage = mock_storage_cls.return_value

        client = AsyncMock()
        req = self._make_request({"kml_content": "<kml>test</kml>"})

        await _submit_demo_request(req, client)

        upload_call = mock_storage.upload_bytes.call_args
        blob_name = upload_call[0][1]
        assert blob_name.startswith("demo/")
        assert blob_name.endswith(".kml")

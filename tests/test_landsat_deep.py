"""Tests for Landsat deep integration (#612).

Covers:
- Frame plan includes Landsat frames for 2013-2017 pre-Sentinel period
- Landsat frames use correct collection and are not flagged as NAIP
- NDVI pipeline routes Landsat frames through compute_landsat_ndvi
- Frame metadata labels Landsat source distinctly
- QA_PIXEL cloud masking (bit flag logic)
- STAC search for Landsat scenes (mocked)
- Cross-sensor timeline continuity (Landsat → Sentinel-2)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from treesight.pipeline.enrichment.frames import build_frame_plan

# Kenya coords — outside CONUS so no NAIP contamination
KENYA_COORDS = [
    [36.8, -1.3],
    [36.81, -1.3],
    [36.81, -1.31],
    [36.8, -1.31],
    [36.8, -1.3],
]

# US coords — inside CONUS to test NAIP+Landsat interaction
US_COORDS = [
    [-100.0, 40.0],
    [-99.9, 40.0],
    [-99.9, 39.9],
    [-100.0, 39.9],
    [-100.0, 40.0],
]


# ---------------------------------------------------------------------------
# §1 — Frame plan includes Landsat years
# ---------------------------------------------------------------------------


class TestLandsatFramePlan:
    """Landsat frames should appear for 2013-2017 in the frame plan."""

    def test_landsat_frames_present_for_pre_sentinel_years(self):
        frames = build_frame_plan(KENYA_COORDS)
        landsat_frames = [f for f in frames if f["collection"] == "landsat-c2-l2"]
        assert len(landsat_frames) > 0, "Expected Landsat frames for pre-2018 years"

    def test_landsat_frames_cover_2013_to_2017(self):
        frames = build_frame_plan(KENYA_COORDS)
        landsat_years = sorted({f["year"] for f in frames if f["collection"] == "landsat-c2-l2"})
        assert 2013 in landsat_years
        assert 2017 in landsat_years

    def test_landsat_frames_are_seasonal(self):
        """Each Landsat year should have 4 seasonal frames."""
        frames = build_frame_plan(KENYA_COORDS)
        landsat_frames = [f for f in frames if f["collection"] == "landsat-c2-l2"]
        # Group by year
        by_year: dict[int, list] = {}
        for f in landsat_frames:
            by_year.setdefault(f["year"], []).append(f)
        for year, year_frames in by_year.items():
            seasons = {f["season"] for f in year_frames}
            assert seasons == {"winter", "spring", "summer", "autumn"}, (
                f"Year {year} missing seasons: got {seasons}"
            )

    def test_landsat_frames_not_flagged_as_naip(self):
        frames = build_frame_plan(KENYA_COORDS)
        landsat_frames = [f for f in frames if f["collection"] == "landsat-c2-l2"]
        for f in landsat_frames:
            assert f["is_naip"] is False

    def test_landsat_frames_precede_sentinel_frames(self):
        """Landsat frames should come before Sentinel-2 frames in timeline."""
        frames = build_frame_plan(KENYA_COORDS)
        landsat_end = max(f["end"] for f in frames if f["collection"] == "landsat-c2-l2")
        sentinel_start = min(f["start"] for f in frames if f["collection"] == "sentinel-2-l2a")
        # Landsat ends ≤ Sentinel-2 starts (or overlap in 2017-2018)
        assert landsat_end <= sentinel_start or int(landsat_end[:4]) <= 2018

    def test_date_filter_excludes_landsat_frames(self):
        """date_start after 2018 should exclude all Landsat frames."""
        frames = build_frame_plan(KENYA_COORDS, date_start="2019-01-01")
        landsat_frames = [f for f in frames if f["collection"] == "landsat-c2-l2"]
        assert len(landsat_frames) == 0

    def test_date_filter_includes_only_landsat(self):
        """date_end before 2017 should yield only Landsat frames."""
        frames = build_frame_plan(KENYA_COORDS, date_end="2016-12-31")
        collections = {f["collection"] for f in frames}
        assert "landsat-c2-l2" in collections
        assert "sentinel-2-l2a" not in collections

    def test_max_history_years_caps_landsat(self):
        """max_history_years=3 from 2026 should exclude 2013-2022."""
        frames = build_frame_plan(KENYA_COORDS, max_history_years=3)
        years = {f["year"] for f in frames}
        assert 2013 not in years
        assert 2017 not in years

    def test_us_coords_have_both_naip_and_landsat(self):
        """US locations should have NAIP, Landsat, and Sentinel-2 frames."""
        frames = build_frame_plan(US_COORDS)
        collections = {f["collection"] for f in frames}
        assert "landsat-c2-l2" in collections
        assert "naip" in collections
        assert "sentinel-2-l2a" in collections

    def test_monthly_cadence_excludes_landsat(self):
        """Monthly cadence is for Pro/Team — Landsat only in seasonal cadence."""
        frames = build_frame_plan(KENYA_COORDS, cadence="monthly")
        landsat_frames = [f for f in frames if f["collection"] == "landsat-c2-l2"]
        assert len(landsat_frames) == 0


# ---------------------------------------------------------------------------
# §2 — QA_PIXEL bit flag logic
# ---------------------------------------------------------------------------


class TestQaPixelMask:
    """Landsat QA_PIXEL cloud/shadow/snow bit masking."""

    def test_clear_mask_constant(self):
        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_CLEAR_MASK

        # Bits 1 (dilated cloud), 3 (cloud), 4 (cloud shadow), 5 (snow)
        assert _LANDSAT_QA_CLEAR_MASK == 0b00111010

    def test_clear_pixel_passes_mask(self):
        """A pixel with no cloud/shadow/snow bits set should pass."""
        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_CLEAR_MASK

        qa_value = np.uint16(0b0000000001000001)  # bit 0=fill, bit 6=clear
        is_cloudy = (qa_value & _LANDSAT_QA_CLEAR_MASK) != 0
        assert not is_cloudy, "Clear pixel should pass the mask"

    def test_cloudy_pixel_fails_mask(self):
        """A pixel with cloud bit (bit 3) set should fail."""
        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_CLEAR_MASK

        qa_value = np.uint16(0b0000000000001000)  # bit 3 = cloud
        is_cloudy = (qa_value & _LANDSAT_QA_CLEAR_MASK) != 0
        assert is_cloudy, "Cloudy pixel should fail the mask"

    def test_cloud_shadow_fails_mask(self):
        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_CLEAR_MASK

        qa_value = np.uint16(0b0000000000010000)  # bit 4 = cloud shadow
        is_cloudy = (qa_value & _LANDSAT_QA_CLEAR_MASK) != 0
        assert is_cloudy

    def test_snow_fails_mask(self):
        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_CLEAR_MASK

        qa_value = np.uint16(0b0000000000100000)  # bit 5 = snow
        is_cloudy = (qa_value & _LANDSAT_QA_CLEAR_MASK) != 0
        assert is_cloudy

    def test_dilated_cloud_fails_mask(self):
        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_CLEAR_MASK

        qa_value = np.uint16(0b0000000000000010)  # bit 1 = dilated cloud
        is_cloudy = (qa_value & _LANDSAT_QA_CLEAR_MASK) != 0
        assert is_cloudy


# ---------------------------------------------------------------------------
# §3 — STAC search mock
# ---------------------------------------------------------------------------


class TestFindBestLandsatScene:
    """Mocked STAC search for Landsat scenes."""

    def _make_mock_item(
        self, item_id, assets, cloud_cover=5.2, dt="2015-07-15T00:00:00Z", epsg=32637
    ):
        item = MagicMock()
        item.id = item_id
        item.assets = assets
        item.properties = {
            "eo:cloud_cover": cloud_cover,
            "datetime": dt,
            "proj:epsg": epsg,
        }
        return item

    def test_returns_scene_dict(self):
        from treesight.pipeline.enrichment.ndvi import _find_best_landsat_scene

        mock_item = self._make_mock_item(
            "LC08_L2SP_170060_20150715",
            {
                "red": MagicMock(href="https://example.com/red.tif"),
                "nir08": MagicMock(href="https://example.com/nir08.tif"),
                "qa_pixel": MagicMock(href="https://example.com/qa.tif"),
            },
        )

        mock_pc = MagicMock()
        mock_pystac = MagicMock()
        mock_search = MagicMock()
        mock_search.items.return_value = [mock_item]
        mock_pystac.Client.open.return_value.search.return_value = mock_search

        with patch.dict(
            "sys.modules", {"planetary_computer": mock_pc, "pystac_client": mock_pystac}
        ):
            result = _find_best_landsat_scene(
                [36.8, -1.3, 36.81, -1.31], "2015-06-01", "2015-09-30"
            )

        assert result is not None
        assert result["scene_id"] == "LC08_L2SP_170060_20150715"
        assert result["red"] == "https://example.com/red.tif"
        assert result["nir"] == "https://example.com/nir08.tif"
        assert result["qa_pixel"] == "https://example.com/qa.tif"
        assert result["cloud_cover"] == 5.2

    def test_returns_none_when_no_items(self):
        from treesight.pipeline.enrichment.ndvi import _find_best_landsat_scene

        mock_pc = MagicMock()
        mock_pystac = MagicMock()
        mock_search = MagicMock()
        mock_search.items.return_value = []
        mock_pystac.Client.open.return_value.search.return_value = mock_search

        with patch.dict(
            "sys.modules", {"planetary_computer": mock_pc, "pystac_client": mock_pystac}
        ):
            result = _find_best_landsat_scene(
                [36.8, -1.3, 36.81, -1.31], "2015-06-01", "2015-09-30"
            )

        assert result is None

    def test_returns_none_when_missing_bands(self):
        from treesight.pipeline.enrichment.ndvi import _find_best_landsat_scene

        mock_item = self._make_mock_item(
            "LC08_BAD",
            {"red": MagicMock(href="x")},  # missing nir08
            cloud_cover=1.0,
            dt="2015-07-15",
        )

        mock_pc = MagicMock()
        mock_pystac = MagicMock()
        mock_search = MagicMock()
        mock_search.items.return_value = [mock_item]
        mock_pystac.Client.open.return_value.search.return_value = mock_search

        with patch.dict(
            "sys.modules", {"planetary_computer": mock_pc, "pystac_client": mock_pystac}
        ):
            result = _find_best_landsat_scene(
                [36.8, -1.3, 36.81, -1.31], "2015-06-01", "2015-09-30"
            )

        assert result is None


# ---------------------------------------------------------------------------
# §4 — NDVI pipeline routes Landsat frames
# ---------------------------------------------------------------------------


class TestLandsatNdviRouting:
    """Landsat frames should be routed through compute_landsat_ndvi."""

    @patch("treesight.pipeline.enrichment.runner.compute_landsat_ndvi")
    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_landsat_frame_uses_landsat_ndvi(self, mock_mosaic, mock_s2_ndvi, mock_ls_ndvi):
        from treesight.pipeline.enrichment.runner import _run_mosaic_ndvi_phase

        frames = [
            {
                "year": 2015,
                "season": "summer",
                "collection": "landsat-c2-l2",
                "is_naip": False,
                "start": "2015-06-01",
                "end": "2015-08-31",
            }
        ]
        mock_mosaic.return_value = "sid-test"
        mock_ls_ndvi.return_value = {
            "mean": 0.65,
            "scene_id": "LC08_test",
            "source": "landsat-c2-l2",
        }
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0], [-49.0, -10.0]],
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]],
            frames,
            "proj",
            "ts",
            "out",
            storage,
            results,
        )

        mock_ls_ndvi.assert_called_once()
        mock_s2_ndvi.assert_not_called()

    @patch("treesight.pipeline.enrichment.runner.compute_landsat_ndvi")
    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_sentinel_frame_still_uses_s2_ndvi(self, mock_mosaic, mock_s2_ndvi, mock_ls_ndvi):
        from treesight.pipeline.enrichment.runner import _run_mosaic_ndvi_phase

        frames = [
            {
                "year": 2024,
                "season": "spring",
                "collection": "sentinel-2-l2a",
                "is_naip": False,
                "start": "2024-03-01",
                "end": "2024-06-01",
            }
        ]
        mock_mosaic.return_value = "sid-test"
        mock_s2_ndvi.return_value = {"mean": 0.7, "scene_id": "S2_test"}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0], [-49.0, -10.0]],
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]],
            frames,
            "proj",
            "ts",
            "out",
            storage,
            results,
        )

        mock_s2_ndvi.assert_called_once()
        mock_ls_ndvi.assert_not_called()


# ---------------------------------------------------------------------------
# §5 — Frame labelling
# ---------------------------------------------------------------------------


class TestLandsatFrameLabelling:
    """Landsat frames must be labelled distinctly from Sentinel-2."""

    @patch("treesight.pipeline.enrichment.runner.compute_landsat_ndvi")
    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_landsat_frame_label_contains_landsat(self, mock_mosaic, mock_s2, mock_ls):
        from treesight.pipeline.enrichment.runner import _run_mosaic_ndvi_phase

        frames = [
            {
                "year": 2015,
                "season": "summer",
                "collection": "landsat-c2-l2",
                "is_naip": False,
                "start": "2015-06-01",
                "end": "2015-08-31",
            }
        ]
        mock_mosaic.return_value = "sid"
        mock_ls.return_value = {"mean": 0.6, "scene_id": "LC08_x", "source": "landsat-c2-l2"}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0], [-49.0, -10.0]],
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]],
            frames,
            "proj",
            "ts",
            "out",
            storage,
            results,
        )

        assert "Landsat" in frames[0]["label"]
        assert "30" in frames[0]["info"]  # 30m resolution

    @patch("treesight.pipeline.enrichment.runner.compute_ndvi")
    @patch("treesight.pipeline.enrichment.runner.register_mosaic")
    def test_sentinel_frame_label_unchanged(self, mock_mosaic, mock_s2):
        from treesight.pipeline.enrichment.runner import _run_mosaic_ndvi_phase

        frames = [
            {
                "year": 2024,
                "season": "spring",
                "collection": "sentinel-2-l2a",
                "is_naip": False,
                "start": "2024-03-01",
                "end": "2024-06-01",
            }
        ]
        mock_mosaic.return_value = "sid"
        mock_s2.return_value = {"mean": 0.7, "scene_id": "S2x"}
        storage = MagicMock()
        results: dict = {}

        _run_mosaic_ndvi_phase(
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0], [-49.0, -10.0]],
            [[-50.0, -10.0], [-50.0, -9.0], [-49.0, -9.0]],
            frames,
            "proj",
            "ts",
            "out",
            storage,
            results,
        )

        assert "Sentinel-2" in frames[0]["info"]
        assert "Landsat" not in frames[0]["info"]


# ---------------------------------------------------------------------------
# §6 — Cross-sensor timeline continuity
# ---------------------------------------------------------------------------


class TestCrossSensorTimeline:
    """Full frame plan should give continuous coverage from 2013 to present."""

    def test_no_gap_between_landsat_and_sentinel(self):
        frames = build_frame_plan(KENYA_COORDS)
        years_by_collection: dict[str, set[int]] = {}
        for f in frames:
            years_by_collection.setdefault(f["collection"], set()).add(f["year"])

        landsat_years = years_by_collection.get("landsat-c2-l2", set())
        sentinel_years = years_by_collection.get("sentinel-2-l2a", set())
        # Landsat should end at or overlap with Sentinel-2 start
        assert max(landsat_years) >= min(sentinel_years) - 1, (
            f"Gap between Landsat (max {max(landsat_years)}) and "
            f"Sentinel-2 (min {min(sentinel_years)})"
        )

    def test_total_coverage_from_2013_to_current(self):
        frames = build_frame_plan(KENYA_COORDS)
        all_years = sorted({f["year"] for f in frames})
        assert all_years[0] == 2013
        assert all_years[-1] >= 2025

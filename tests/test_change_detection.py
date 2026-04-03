"""Tests for change detection — raster-level NDVI comparison (#85)."""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import rasterio

from tests.tiff_helpers import make_ndvi_tiff


def _make_ndvi_tiff(
    data: np.ndarray,
    bounds: tuple[float, float, float, float] = (0, 0, 100, 100),
) -> bytes:
    """Delegate to shared helper in tiff_helpers."""
    return make_ndvi_tiff(data, bounds=bounds)


class TestComputeChangeMap:
    def test_uniform_no_change(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        ndvi = np.full((10, 10), 0.5, dtype=np.float32)
        tiff = _make_ndvi_tiff(ndvi)
        result = compute_change_map(tiff, tiff)

        assert result is not None
        assert abs(result["mean_delta"]) < 0.001
        assert result["loss_ha"] == 0.0
        assert result["gain_ha"] == 0.0
        assert result["valid_pixels"] == 100

    def test_detects_loss(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        before = np.full((10, 10), 0.6, dtype=np.float32)
        after = np.full((10, 10), 0.3, dtype=np.float32)  # -0.3 drop
        tiff_a = _make_ndvi_tiff(before)
        tiff_b = _make_ndvi_tiff(after)

        result = compute_change_map(tiff_a, tiff_b)
        assert result is not None
        assert result["mean_delta"] < -0.2
        assert result["loss_pct"] == 100.0  # all pixels declined > threshold
        assert result["loss_ha"] > 0

    def test_detects_gain(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        before = np.full((10, 10), 0.3, dtype=np.float32)
        after = np.full((10, 10), 0.6, dtype=np.float32)  # +0.3 gain
        tiff_a = _make_ndvi_tiff(before)
        tiff_b = _make_ndvi_tiff(after)

        result = compute_change_map(tiff_a, tiff_b)
        assert result is not None
        assert result["mean_delta"] > 0.2
        assert result["gain_pct"] == 100.0
        assert result["gain_ha"] > 0

    def test_mixed_change(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        before = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.float32)
        after = np.array([[0.3, 0.7], [0.5, 0.5]], dtype=np.float32)
        tiff_a = _make_ndvi_tiff(before)
        tiff_b = _make_ndvi_tiff(after)

        result = compute_change_map(tiff_a, tiff_b)
        assert result is not None
        assert abs(result["mean_delta"]) < 0.05  # roughly balanced
        # 1 loss pixel, 1 gain pixel, 2 stable
        assert result["loss_pct"] == 25.0
        assert result["gain_pct"] == 25.0

    def test_handles_nan_pixels(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        before = np.array([[0.5, np.nan], [0.5, 0.5]], dtype=np.float32)
        after = np.array([[0.5, 0.5], [np.nan, 0.5]], dtype=np.float32)
        tiff_a = _make_ndvi_tiff(before)
        tiff_b = _make_ndvi_tiff(after)

        result = compute_change_map(tiff_a, tiff_b)
        assert result is not None
        # Only pixels valid in BOTH rasters count
        assert result["valid_pixels"] == 2

    def test_returns_none_all_nan(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        nan_arr = np.full((5, 5), np.nan, dtype=np.float32)
        tiff = _make_ndvi_tiff(nan_arr)
        result = compute_change_map(tiff, tiff)
        assert result is None

    def test_change_geotiff_produced(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        before = np.full((4, 4), 0.5, dtype=np.float32)
        after = np.full((4, 4), 0.7, dtype=np.float32)
        result = compute_change_map(_make_ndvi_tiff(before), _make_ndvi_tiff(after))

        assert result is not None
        assert "change_geotiff_bytes" in result
        # Verify it's a valid GeoTIFF
        with rasterio.open(io.BytesIO(result["change_geotiff_bytes"])) as src:
            data = src.read(1)
            assert data.shape == (4, 4)
            assert abs(float(np.nanmean(data)) - 0.2) < 0.01

    def test_custom_thresholds(self):
        from treesight.pipeline.enrichment.change_detection import compute_change_map

        before = np.full((4, 4), 0.5, dtype=np.float32)
        after = np.full((4, 4), 0.55, dtype=np.float32)  # +0.05 (small)

        # Default threshold (0.1) → no gain detected
        result_default = compute_change_map(_make_ndvi_tiff(before), _make_ndvi_tiff(after))
        assert result_default is not None
        assert result_default["gain_pct"] == 0.0  # below 0.1 threshold

        # Lower threshold (0.03) → gain detected
        result_custom = compute_change_map(
            _make_ndvi_tiff(before),
            _make_ndvi_tiff(after),
            gain_threshold=0.03,
        )
        assert result_custom is not None
        assert result_custom["gain_pct"] == 100.0


class TestDetectChanges:
    def _make_frame_plan(self) -> list[dict[str, Any]]:
        return [
            {"year": 2022, "season": "summer", "label": "Summer 2022"},
            {"year": 2023, "season": "summer", "label": "Summer 2023"},
            {"year": 2022, "season": "winter", "label": "Winter 2022"},
            {"year": 2023, "season": "winter", "label": "Winter 2023"},
        ]

    def _make_raster_paths(self) -> list[str | None]:
        return [
            "enrichment/test/t1/ndvi/2022_summer.tif",
            "enrichment/test/t1/ndvi/2023_summer.tif",
            "enrichment/test/t1/ndvi/2022_winter.tif",
            "enrichment/test/t1/ndvi/2023_winter.tif",
        ]

    def test_produces_season_changes(self):
        from treesight.pipeline.enrichment.change_detection import detect_changes

        before = np.full((10, 10), 0.5, dtype=np.float32)
        after = np.full((10, 10), 0.6, dtype=np.float32)
        tiff_before = _make_ndvi_tiff(before)
        tiff_after = _make_ndvi_tiff(after)

        mock_storage = MagicMock()
        mock_storage.download_bytes.side_effect = lambda _c, p: (
            tiff_before if "2022" in p else tiff_after
        )

        result = detect_changes(
            frame_plan=self._make_frame_plan(),
            ndvi_raster_paths=self._make_raster_paths(),
            output_container="test-container",
            project_name="test",
            timestamp="t1",
            storage=mock_storage,
        )

        assert len(result["season_changes"]) == 2  # summer + winter
        assert result["summary"]["comparisons"] == 2
        assert result["summary"]["trajectory"] == "Improving"  # +0.1 > 0.02 threshold

    def test_skips_seasons_with_single_year(self):
        from treesight.pipeline.enrichment.change_detection import detect_changes

        frames = [
            {"year": 2022, "season": "summer", "label": "Summer 2022"},
            {"year": 2023, "season": "summer", "label": "Summer 2023"},
            {"year": 2022, "season": "autumn", "label": "Autumn 2022"},
        ]
        paths = [
            "enrichment/test/t1/ndvi/2022_summer.tif",
            "enrichment/test/t1/ndvi/2023_summer.tif",
            "enrichment/test/t1/ndvi/2022_autumn.tif",
        ]

        ndvi = np.full((5, 5), 0.5, dtype=np.float32)
        tiff = _make_ndvi_tiff(ndvi)

        mock_storage = MagicMock()
        mock_storage.download_bytes.return_value = tiff

        result = detect_changes(
            frame_plan=frames,
            ndvi_raster_paths=paths,
            output_container="c",
            project_name="p",
            timestamp="t",
            storage=mock_storage,
        )

        # Only summer has 2 years; autumn has 1
        assert result["summary"]["comparisons"] == 1

    def test_handles_missing_raster_paths(self):
        from treesight.pipeline.enrichment.change_detection import detect_changes

        frames = self._make_frame_plan()
        paths: list[str | None] = [None, None, None, None]

        result = detect_changes(
            frame_plan=frames,
            ndvi_raster_paths=paths,
            output_container="c",
            project_name="p",
            timestamp="t",
            storage=MagicMock(),
        )

        assert result["summary"]["comparisons"] == 0
        assert result["summary"]["trajectory"] == "Insufficient data"

    def test_handles_download_error(self):
        from treesight.pipeline.enrichment.change_detection import detect_changes

        mock_storage = MagicMock()
        mock_storage.download_bytes.side_effect = Exception("blob not found")

        result = detect_changes(
            frame_plan=self._make_frame_plan(),
            ndvi_raster_paths=self._make_raster_paths(),
            output_container="c",
            project_name="p",
            timestamp="t",
            storage=mock_storage,
        )

        assert result["summary"]["comparisons"] == 0

    def test_stores_change_maps(self):
        from treesight.pipeline.enrichment.change_detection import detect_changes

        ndvi = np.full((5, 5), 0.5, dtype=np.float32)
        tiff = _make_ndvi_tiff(ndvi)

        mock_storage = MagicMock()
        mock_storage.download_bytes.return_value = tiff

        detect_changes(
            frame_plan=self._make_frame_plan(),
            ndvi_raster_paths=self._make_raster_paths(),
            output_container="out",
            project_name="proj",
            timestamp="ts",
            storage=mock_storage,
        )

        # Should store 2 change maps (summer + winter)
        assert mock_storage.upload_bytes.call_count == 2
        paths_stored = [call.args[1] for call in mock_storage.upload_bytes.call_args_list]
        assert any("summer" in p for p in paths_stored)
        assert any("winter" in p for p in paths_stored)

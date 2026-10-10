"""Tests for NDVI computation — both COG band-math and tile-based sampling."""

from __future__ import annotations

import io
import struct
import zlib
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helper: build a minimal valid PNG (RGBA, 4x4, filter type 0)
# ---------------------------------------------------------------------------


def _make_test_png(width: int = 4, height: int = 4, red_val: int = 128) -> bytes:
    """Create a minimal RGBA PNG with a uniform red channel."""
    buf = io.BytesIO()
    buf.write(b"\x89PNG\r\n\x1a\n")

    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    _write_chunk(buf, b"IHDR", ihdr_data)

    # IDAT — unfiltered rows (filter type 0)
    raw_rows = b""
    for _ in range(height):
        raw_rows += b"\x00"  # filter type 0 (None)
        for _ in range(width):
            raw_rows += bytes([red_val, 0, 0, 255])  # RGBA

    compressed = zlib.compress(raw_rows)
    _write_chunk(buf, b"IDAT", compressed)

    # IEND
    _write_chunk(buf, b"IEND", b"")

    return buf.getvalue()


def _write_chunk(buf: io.BytesIO, chunk_type: bytes, data: bytes) -> None:
    buf.write(struct.pack(">I", len(data)))
    buf.write(chunk_type)
    buf.write(data)
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    buf.write(struct.pack(">I", crc))


# ---------------------------------------------------------------------------
# Tests for _extract_red_channel_from_png (pure Python PNG parser)
# ---------------------------------------------------------------------------


class TestExtractRedChannel:
    def test_valid_rgba_png(self):
        from treesight.pipeline.enrichment.ndvi import _extract_red_channel_from_png

        png = _make_test_png(4, 4, red_val=200)
        values = _extract_red_channel_from_png(png)
        assert len(values) == 16
        assert all(v == 200 for v in values)

    def test_invalid_header(self):
        from treesight.pipeline.enrichment.ndvi import _extract_red_channel_from_png

        result = _extract_red_channel_from_png(b"not a png")
        assert result == []

    def test_empty_bytes(self):
        from treesight.pipeline.enrichment.ndvi import _extract_red_channel_from_png

        result = _extract_red_channel_from_png(b"")
        assert result == []

    def test_transparent_pixels_excluded(self):
        from treesight.pipeline.enrichment.ndvi import _extract_red_channel_from_png

        # Build PNG with alpha=0 (transparent) pixels
        buf = io.BytesIO()
        buf.write(b"\x89PNG\r\n\x1a\n")
        width, height = 2, 2
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        _write_chunk(buf, b"IHDR", ihdr_data)

        raw_rows = b""
        for row in range(height):
            raw_rows += b"\x00"
            for col in range(width):
                if row == 0 and col == 0:
                    raw_rows += bytes([100, 0, 0, 0])  # transparent
                else:
                    raw_rows += bytes([150, 0, 0, 255])  # opaque
        compressed = zlib.compress(raw_rows)
        _write_chunk(buf, b"IDAT", compressed)
        _write_chunk(buf, b"IEND", b"")

        values = _extract_red_channel_from_png(buf.getvalue())
        assert len(values) == 3  # one transparent pixel excluded
        assert all(v == 150 for v in values)


# ---------------------------------------------------------------------------
# Tests for _paeth_predictor
# ---------------------------------------------------------------------------


class TestPaethPredictor:
    def test_basic_values(self):
        from treesight.pipeline.enrichment.ndvi import _paeth_predictor

        assert _paeth_predictor(0, 0, 0) == 0
        assert _paeth_predictor(10, 10, 10) == 10
        assert _paeth_predictor(1, 2, 3) in (1, 2, 3)  # any valid paeth


# ---------------------------------------------------------------------------
# Tests for fetch_ndvi_stat (tile-based sampling)
# ---------------------------------------------------------------------------


class TestFetchNdviStat:
    def test_returns_stats_on_success(self):
        from treesight.pipeline.enrichment.ndvi import fetch_ndvi_stat

        png = _make_test_png(4, 4, red_val=178)  # maps to NDVI ~0.498
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = png

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        coords = [[-0.5, 51.5], [-0.4, 51.5], [-0.4, 51.4], [-0.5, 51.4]]
        result = fetch_ndvi_stat("test-search-id", coords, client=mock_client)

        assert result is not None
        assert "mean" in result
        assert "min" in result
        assert "max" in result
        assert isinstance(result["mean"], float)
        assert -0.2 <= result["mean"] <= 0.8

    def test_returns_none_on_404(self):
        from treesight.pipeline.enrichment.ndvi import fetch_ndvi_stat

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        coords = [[-0.5, 51.5], [-0.4, 51.5], [-0.4, 51.4]]
        result = fetch_ndvi_stat("test-id", coords, client=mock_client)
        assert result is None

    def test_returns_none_on_exception(self):
        from treesight.pipeline.enrichment.ndvi import fetch_ndvi_stat

        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("network error")

        coords = [[-0.5, 51.5], [-0.4, 51.5]]
        result = fetch_ndvi_stat("test-id", coords, client=mock_client)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for compute_ndvi (COG band-math)
# ---------------------------------------------------------------------------


def _s2_scene_fixture(
    scene_id: str = "S2A_test",
    cloud_cover: float = 5.0,
    with_scl: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scene_id": scene_id,
        "B04": "https://example.com/B04.tif",
        "B08": "https://example.com/B08.tif",
        "cloud_cover": cloud_cover,
        "datetime": "2024-07-15T10:00:00Z",
        "crs": "EPSG:32632",
    }
    if with_scl:
        result["SCL"] = "https://example.com/SCL.tif"
    return result


def _band_profile(rows: int = 10, cols: int = 10) -> dict[str, Any]:
    from rasterio.transform import from_bounds

    return {
        "driver": "GTiff",
        "crs": "EPSG:4326",
        "transform": from_bounds(0, 0, cols * 10, rows * 10, cols, rows),
    }


def _test_geometry() -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[[-1, -1], [1000, -1], [1000, 1000], [-1, 1000], [-1, -1]]],
    }


class TestComputeNdvi:
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene", return_value=None)
    def test_fourth_positional_argument_remains_max_cloud(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        bbox = [0, 0, 4, 4]
        result = compute_ndvi(bbox, "2024-06-01", "2024-08-31", 10.0, geometry=_test_geometry())

        assert result is None
        mock_find.assert_called_once_with(bbox, "2024-06-01", "2024-08-31", 10.0)

    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_returns_none_when_no_scene(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = None
        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())
        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_computes_ndvi_from_bands(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture()

        # B04 (Red) = 1000, B08 (NIR) = 3000 → NDVI = (3000-1000)/(3000+1000) = 0.5
        b04 = np.full((10, 10), 1000, dtype=np.uint16)
        b08 = np.full((10, 10), 3000, dtype=np.uint16)
        profile = _band_profile(10, 10)

        mock_read.side_effect = [(b04, profile), (b08, profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is not None
        assert result["scene_id"] == "S2A_test"
        assert abs(result["mean"] - 0.5) < 0.01
        assert result["valid_pixels"] == 100
        assert result["std"] == 0.0  # uniform values
        assert isinstance(result["geotiff_bytes"], bytes)
        assert len(result["geotiff_bytes"]) > 0

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_insufficient_valid_pixels_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture("S2A_nodata", cloud_cover=10.0)

        # Mix of valid and nodata (0) pixels
        b04 = np.array([[0, 1000], [500, 0]], dtype=np.uint16)
        b08 = np.array([[0, 3000], [2000, 0]], dtype=np.uint16)
        profile = _band_profile(2, 2)
        mock_read.side_effect = [(b04, profile), (b08, profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_handles_shape_mismatch(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture()

        # Different-sized arrays (simulating slight alignment difference)
        b04 = np.full((10, 12), 1000, dtype=np.uint16)
        b08 = np.full((11, 10), 3000, dtype=np.uint16)
        mock_read.side_effect = [
            (b04, _band_profile(10, 12)),
            (b08, _band_profile(11, 10)),
        ]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is not None
        # Should still compute correctly with trimmed arrays
        assert result["valid_pixels"] == 100  # 10 × 10

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_returns_none_all_nodata(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture("S2A_empty", cloud_cover=90.0)

        b04 = np.zeros((5, 5), dtype=np.uint16)
        b08 = np.zeros((5, 5), dtype=np.uint16)
        mock_read.side_effect = [(b04, _band_profile(5, 5)), (b08, _band_profile(5, 5))]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())
        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_handles_exception_gracefully(self, mock_find, mock_read):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture("S2A_err")
        mock_read.side_effect = Exception("COG read timeout")

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())
        assert result is None


# ---------------------------------------------------------------------------
# Tests for transform_bbox (moved to treesight.geo)
# ---------------------------------------------------------------------------


class TestTransformBbox:
    def test_identity_for_same_crs(self):
        from treesight.geo import transform_bbox

        bbox = [-0.5, 51.4, -0.4, 51.5]
        result = transform_bbox(bbox, "EPSG:4326", "EPSG:4326")
        assert result == (-0.5, 51.4, -0.4, 51.5)


# ---------------------------------------------------------------------------
# Tests for _resample_scl (nearest-neighbour upscaling)
# ---------------------------------------------------------------------------


class TestResampleScl:
    def test_identity_when_same_shape(self):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import _resample_scl

        scl = np.array([[4, 5], [2, 9]], dtype=np.uint8)
        result = _resample_scl(scl, (2, 2))
        assert np.array_equal(result, scl)

    def test_upscale_2x(self):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import _resample_scl

        scl = np.array([[4, 9], [5, 8]], dtype=np.uint8)
        result = _resample_scl(scl, (4, 4))
        assert result.shape == (4, 4)
        # Top-left quadrant should be 4 (vegetation)
        assert result[0, 0] == 4
        assert result[0, 1] == 4
        assert result[1, 0] == 4
        # Bottom-right should be 8 (cloud)
        assert result[3, 3] == 8

    def test_preserves_categorical_values(self):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import _resample_scl

        scl = np.array([[0, 11], [3, 6]], dtype=np.uint8)
        result = _resample_scl(scl, (6, 6))
        unique = set(result.flatten())
        assert unique <= {0, 3, 6, 11}


# ---------------------------------------------------------------------------
# Tests for SCL masking in compute_ndvi
# ---------------------------------------------------------------------------


class TestComputeNdviWithScl:
    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scl_masks_cloud_pixels(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        b04 = np.full((4, 4), 1000, dtype=np.uint16)
        b08 = np.full((4, 4), 3000, dtype=np.uint16)
        # SCL at 20m = half resolution: 2x2 → resampled to 4x4
        # class 4 = vegetation (valid), class 9 = cloud (masked)
        scl = np.array([[4, 9], [4, 4]], dtype=np.uint8)
        profile = _band_profile(4, 4)
        scl_profile = _band_profile(2, 2)

        mock_read.side_effect = [(b04, profile), (b08, profile), (scl, scl_profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is not None
        assert result["scl_applied"] is True
        assert result["scl_masked_pixels"] == 4  # top-right 2x2 quadrant masked
        assert result["valid_pixels"] == 12  # 16 total - 4 cloud

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_no_scl_in_scene(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        # Scene without SCL key
        mock_find.return_value = _s2_scene_fixture(with_scl=False)

        b04 = np.full((4, 4), 1000, dtype=np.uint16)
        b08 = np.full((4, 4), 3000, dtype=np.uint16)
        profile = _band_profile(4, 4)

        mock_read.side_effect = [(b04, profile), (b08, profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is not None
        assert result["scl_applied"] is False
        assert result["scl_masked_pixels"] == 0
        assert result["valid_pixels"] == 16

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scl_read_failure_falls_back(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        b04 = np.full((4, 4), 1000, dtype=np.uint16)
        b08 = np.full((4, 4), 3000, dtype=np.uint16)
        profile = _band_profile(4, 4)

        # B04 and B08 succeed, SCL read raises an error
        mock_read.side_effect = [(b04, profile), (b08, profile), Exception("SCL read failed")]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is not None
        # Fallback: SCL not applied, all pixels valid
        assert result["scl_applied"] is False
        assert result["scl_masked_pixels"] == 0
        assert result["valid_pixels"] == 16

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scl_masks_all_pixels_returns_none(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        b04 = np.full((4, 4), 1000, dtype=np.uint16)
        b08 = np.full((4, 4), 3000, dtype=np.uint16)
        # All pixels are cloud (class 9)
        scl = np.full((2, 2), 9, dtype=np.uint8)
        profile = _band_profile(4, 4)
        scl_profile = _band_profile(2, 2)

        mock_read.side_effect = [(b04, profile), (b08, profile), (scl, scl_profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is None  # no valid pixels after masking

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_geotiff_nans_out_scl_masked_pixels(self, mock_find, mock_read):
        """GeoTIFF raster must NaN out cloud/shadow/invalid pixels so that
        downstream change detection only compares clean surface pixels."""
        import numpy as np
        import rasterio

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        b04 = np.full((4, 4), 1000, dtype=np.uint16)
        b08 = np.full((4, 4), 3000, dtype=np.uint16)
        # SCL 2x2 → resampled to 4x4: top-right quadrant is cloud (9)
        scl = np.array([[4, 9], [4, 4]], dtype=np.uint8)
        profile = _band_profile(4, 4)
        scl_profile = _band_profile(2, 2)
        mock_read.side_effect = [(b04, profile), (b08, profile), (scl, scl_profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())
        assert result is not None

        with rasterio.open(io.BytesIO(result["geotiff_bytes"])) as src:
            data = src.read(1)
            # Cloud-masked pixels should be NaN in the GeoTIFF
            nan_count = int(np.isnan(data).sum())
            valid_count = int(np.isfinite(data).sum())
            assert nan_count == 4, f"Expected 4 NaN (cloud) pixels, got {nan_count}"
            assert valid_count == 12, f"Expected 12 valid pixels, got {valid_count}"
            # Valid pixels should have NDVI = 0.5
            valid_vals = data[np.isfinite(data)]
            assert np.allclose(valid_vals, 0.5, atol=0.01)


class TestComputeNdviPolygonMask:
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_missing_geometry_returns_unavailable_without_scene_lookup(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        result = compute_ndvi([0, 0, 4, 4], "2024-06-01", "2024-08-31")

        assert result is None
        mock_find.assert_not_called()

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_zero_in_plot_pixels_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture()
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        profile = _band_profile(4, 4)
        mock_read.side_effect = [(red, profile), (nir, profile)]
        geometry = {
            "type": "Polygon",
            "coordinates": [[[100, 100], [101, 100], [101, 101], [100, 101], [100, 100]]],
        }

        result = compute_ndvi([0, 0, 4, 4], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_one_in_plot_pixel_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture()
        red = np.array([[1000, 0], [0, 0]], dtype=np.uint16)
        nir = np.array([[3000, 0], [0, 0]], dtype=np.uint16)
        profile = _band_profile(2, 2)
        mock_read.side_effect = [(red, profile), (nir, profile)]
        geometry = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]],
        }

        result = compute_ndvi([0, 0, 20, 20], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_plot_mask_excludes_outside_and_hole_pixels(self, mock_find, mock_read):
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture()
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        red[0, 0], nir[0, 0] = 1000, 19000  # outside the plot
        red[3, 0], nir[3, 0] = 1000, 19000  # inside a plot hole
        red[0, 3], nir[0, 3] = 9000, 11000  # clearing inside the plot
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 4, 4),
        }
        mock_read.side_effect = [(red, profile), (nir, profile)]
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
                    [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75], [0.25, 0.25]],
                ],
                [[[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]],
            ],
        }

        result = compute_ndvi(
            [0, 0, 4, 4],
            "2024-06-01",
            "2024-08-31",
            geometry=geometry,
        )

        assert result is not None
        assert result["geometry_mask_applied"] is True
        assert result["mean"] < 0.5
        assert result["valid_pixels"] == 7
        assert result["total_pixels"] == 7
        with rasterio.open(io.BytesIO(result["geotiff_bytes"])) as raster:
            ndvi = raster.read(1)
        assert np.isnan(ndvi[0, 0])
        assert np.isnan(ndvi[3, 0])
        assert np.isclose(ndvi[0, 3], 0.1, atol=0.01)

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scl_masked_count_excludes_pixels_outside_plot(self, mock_find, mock_read):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        scl = np.array([[4, 4], [9, 9]], dtype=np.uint8)
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 4, 4),
        }
        scl_profile = _band_profile(2, 2)
        mock_read.side_effect = [(red, profile), (nir, profile), (scl, scl_profile)]
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
                    [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75], [0.25, 0.25]],
                ],
                [[[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]],
            ],
        }

        result = compute_ndvi([0, 0, 4, 4], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is not None
        assert result["total_pixels"] == 7
        assert result["scl_masked_pixels"] == 3
        assert result["valid_pixels"] == 4


class TestComputeLandsatNdviPolygonMask:
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene", return_value=None)
    def test_fourth_positional_argument_remains_max_cloud(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        bbox = [0, 0, 4, 4]
        result = compute_landsat_ndvi(bbox, "2015-06-01", "2015-08-31", 12.0, geometry=_test_geometry())

        assert result is None
        mock_find.assert_called_once_with(bbox, "2015-06-01", "2015-08-31", 12.0)

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_one_valid_pixel_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_one_pixel",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        red = np.array([[1000, 0], [0, 0]], dtype=np.uint16)
        nir = np.array([[3000, 0], [0, 0]], dtype=np.uint16)
        profile = _band_profile(2, 2)
        mock_read.side_effect = [(red, profile), (nir, profile)]
        geometry = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]],
        }

        result = compute_landsat_ndvi([0, 0, 20, 20], "2015-06-01", "2015-08-31", geometry=geometry)

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_plot_mask_excludes_outside_and_hole_pixels(self, mock_find, mock_read):
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_test",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        red[0, 0], nir[0, 0] = 1000, 19000
        red[2, 1], nir[2, 1] = 1000, 19000
        red[3, 3], nir[3, 3] = 9000, 11000
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 4, 4),
        }
        mock_read.side_effect = [(red, profile), (nir, profile)]
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [4, 0], [4, 4], [2, 4], [0, 2], [0, 0]],
                [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
            ],
        }

        result = compute_landsat_ndvi(
            [0, 0, 4, 4],
            "2015-06-01",
            "2015-08-31",
            geometry=geometry,
        )

        assert result is not None
        assert result["geometry_mask_applied"] is True
        assert result["mean"] < 0.5
        assert result["valid_pixels"] < 16
        assert result["total_pixels"] == 12
        with rasterio.open(io.BytesIO(result["geotiff_bytes"])) as raster:
            ndvi = raster.read(1)
        assert np.isnan(ndvi[0, 0])
        assert np.isnan(ndvi[2, 1])
        assert np.isclose(ndvi[3, 3], 0.1, atol=0.01)

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_qa_masked_count_excludes_pixels_outside_plot(self, mock_find, mock_read):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_CLEAR_MASK, compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_masked",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "qa_pixel": "https://example.com/qa.tif",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        qa = np.array([[_LANDSAT_QA_CLEAR_MASK, 0], [_LANDSAT_QA_CLEAR_MASK, _LANDSAT_QA_CLEAR_MASK]], dtype=np.uint16)
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 4, 4),
        }
        qa_profile = _band_profile(2, 2)
        mock_read.side_effect = [(red, profile), (nir, profile), (qa, qa_profile)]
        geometry = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
                    [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75], [0.25, 0.25]],
                ],
                [[[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]],
            ],
        }

        result = compute_landsat_ndvi([0, 0, 4, 4], "2015-06-01", "2015-08-31", geometry=geometry)

        assert result is not None
        assert result["total_pixels"] == 7
        assert result["qa_masked_pixels"] == 3
        assert result["valid_pixels"] == 4


def test_cog_band_read_transform_matches_read_window(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from treesight.pipeline.enrichment.ndvi import _cog_band_read

    source_path = tmp_path / "fractional-window.tif"
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 10, 1, 1),
    ) as destination:
        destination.write(np.arange(100, dtype=np.uint8).reshape(10, 10), 1)

    data, profile = _cog_band_read(str(source_path), [0.2, 0.2, 5.6, 5.6])

    assert data.shape == (6, 6)
    assert data[0, 0] == 40
    assert data[5, 5] == 95
    assert profile["transform"] == from_origin(0, 6, 1, 1)

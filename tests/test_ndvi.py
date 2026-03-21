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
) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "B04": "https://example.com/B04.tif",
        "B08": "https://example.com/B08.tif",
        "cloud_cover": cloud_cover,
        "datetime": "2024-07-15T10:00:00Z",
        "crs": "EPSG:32632",
    }


def _band_profile(rows: int = 10, cols: int = 10) -> dict[str, Any]:
    from rasterio.transform import from_bounds

    return {
        "driver": "GTiff",
        "crs": "EPSG:32632",
        "transform": from_bounds(0, 0, cols * 10, rows * 10, cols, rows),
    }


class TestComputeNdvi:
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_returns_none_when_no_scene(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = None
        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31")
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

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31")

        assert result is not None
        assert result["scene_id"] == "S2A_test"
        assert abs(result["mean"] - 0.5) < 0.01
        assert result["valid_pixels"] == 100
        assert result["std"] == 0.0  # uniform values
        assert isinstance(result["geotiff_bytes"], bytes)
        assert len(result["geotiff_bytes"]) > 0

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_handles_nodata_pixels(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture("S2A_nodata", cloud_cover=10.0)

        # Mix of valid and nodata (0) pixels
        b04 = np.array([[0, 1000], [500, 0]], dtype=np.uint16)
        b08 = np.array([[0, 3000], [2000, 0]], dtype=np.uint16)
        profile = _band_profile(2, 2)
        mock_read.side_effect = [(b04, profile), (b08, profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31")

        assert result is not None
        assert result["valid_pixels"] == 2  # only 2 non-zero pixels

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

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31")

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

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31")
        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_handles_exception_gracefully(self, mock_find, mock_read):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture("S2A_err")
        mock_read.side_effect = Exception("COG read timeout")

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31")
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _transform_bbox_4326
# ---------------------------------------------------------------------------


class TestTransformBbox4326:
    def test_identity_for_4326(self):
        from treesight.pipeline.enrichment.ndvi import _transform_bbox_4326

        bbox = [-0.5, 51.4, -0.4, 51.5]
        result = _transform_bbox_4326(bbox, "EPSG:4326")
        assert result == (-0.5, 51.4, -0.4, 51.5)

    def test_case_insensitive_4326(self):
        from treesight.pipeline.enrichment.ndvi import _transform_bbox_4326

        bbox = [-0.5, 51.4, -0.4, 51.5]
        result = _transform_bbox_4326(bbox, "epsg:4326")
        assert result == (-0.5, 51.4, -0.4, 51.5)

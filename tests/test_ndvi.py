"""Tests for NDVI computation — both COG band-math and tile-based sampling."""

from __future__ import annotations

import io
import struct
import zlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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
        "transform": from_bounds(-0.5, 51.4, -0.4, 51.5, cols, rows),
    }


def _test_plot_geometry():
    from treesight.models.geometry import PolygonGeometry, PolygonPart

    return PolygonGeometry(
        parts=(
            PolygonPart(
                outer=(
                    (-0.5, 51.4),
                    (-0.4, 51.4),
                    (-0.4, 51.5),
                    (-0.5, 51.5),
                    (-0.5, 51.4),
                ),
            ),
        ),
    )


class TestComputeNdvi:
    def test_missing_geometry_is_explicitly_unavailable(self):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31")

        assert result == {"available": False, "unavailable_reason": "geometry_unavailable"}

    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_returns_none_when_no_scene(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = None
        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )
        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_computes_ndvi_from_bands(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        # B04 (Red) = 1000, B08 (NIR) = 3000 → NDVI = (3000-1000)/(3000+1000) = 0.5
        b04 = np.full((10, 10), 1000, dtype=np.uint16)
        b08 = np.full((10, 10), 3000, dtype=np.uint16)
        profile = _band_profile(10, 10)

        scl = np.full((10, 10), 4, dtype=np.uint8)
        mock_read.side_effect = [(b04, profile), (b08, profile), (scl, profile)]

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

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

        mock_find.return_value = _s2_scene_fixture(
            "S2A_nodata",
            cloud_cover=10.0,
            with_scl=True,
        )

        # Mix of valid and nodata (0) pixels
        b04 = np.array([[0, 1000], [500, 0]], dtype=np.uint16)
        b08 = np.array([[0, 3000], [2000, 0]], dtype=np.uint16)
        profile = _band_profile(2, 2)
        scl = np.full((2, 2), 4, dtype=np.uint8)
        mock_read.side_effect = [(b04, profile), (b08, profile), (scl, profile)]

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result is not None
        assert result["valid_pixels"] == 2  # only 2 non-zero pixels

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_rejects_misaligned_reflectance_grids(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        b04 = np.full((10, 12), 1000, dtype=np.uint16)
        b08 = np.full((11, 10), 3000, dtype=np.uint16)
        mock_read.side_effect = [
            (b04, _band_profile(10, 12)),
            (b08, _band_profile(11, 10)),
        ]

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result == {
            "available": False,
            "unavailable_reason": "misaligned_band_grids",
        }

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_rejects_same_shape_bands_on_different_grids(self, mock_find, mock_read):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red_profile = _band_profile(4, 4)
        nir_profile = {
            **red_profile,
            "transform": from_bounds(-0.49, 51.4, -0.39, 51.5, 4, 4),
        }
        band = np.full((4, 4), 1000, dtype=np.uint16)
        mock_read.side_effect = [
            (band, red_profile),
            (band, nir_profile),
        ]

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result == {
            "available": False,
            "unavailable_reason": "misaligned_band_grids",
        }

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_returns_none_all_nodata(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(
            "S2A_empty",
            cloud_cover=90.0,
            with_scl=True,
        )

        b04 = np.zeros((5, 5), dtype=np.uint16)
        b08 = np.zeros((5, 5), dtype=np.uint16)
        profile = _band_profile(5, 5)
        scl = np.full((5, 5), 4, dtype=np.uint8)
        mock_read.side_effect = [(b04, profile), (b08, profile), (scl, profile)]

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )
        assert result == {
            "available": False,
            "unavailable_reason": "insufficient_in_plot_pixels",
            "valid_pixels": 0,
            "geometry_pixels": 25,
            "total_pixels": 25,
            "grid_pixels": 25,
            "geometry_masked_pixels": 0,
            "geometry_mask_applied": True,
            "geometry_mask_method": "pixel_center",
        }

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_plot_mask_excludes_outside_and_hole_pixels(self, mock_find, mock_read):
        import io

        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        from treesight.models.geometry import PolygonGeometry, PolygonPart
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture("S2A_plot_mask", with_scl=True)
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_bounds(0, 0, 5, 5, 5, 5),
        }
        red = np.full((5, 5), 1000, dtype=np.uint16)
        nir = np.full((5, 5), 3000, dtype=np.uint16)
        # Low NDVI outside the plot and inside its hole must not affect stats.
        red[0, 0] = red[2, 2] = 3000
        nir[0, 0] = nir[2, 2] = 1000
        geometry = PolygonGeometry(
            parts=(
                PolygonPart(
                    outer=((1, 1), (4, 1), (4, 4), (1, 4), (1, 1)),
                    inners=(((2, 2), (3, 2), (3, 3), (2, 3), (2, 2)),),
                ),
            ),
        )
        scl = np.full((5, 5), 4, dtype=np.uint8)
        mock_read.side_effect = [(red, profile), (nir, profile), (scl, profile)]

        result = compute_ndvi([0, 0, 5, 5], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is not None
        assert result["mean"] == pytest.approx(0.5)
        assert result["valid_pixels"] == 8
        assert result["geometry_mask_applied"] is True
        assert result["geometry_mask_method"] == "pixel_center"
        with rasterio.open(io.BytesIO(result["geotiff_bytes"])) as src:
            ndvi = src.read(1)
            assert np.isnan(ndvi[0, 0])
            assert np.isnan(ndvi[2, 2])
            assert np.isfinite(ndvi[1, 1])

        # A real in-plot change remains visible to the same masked statistic.
        red[1, 1] = 3000
        nir[1, 1] = 1000
        scl = np.full((5, 5), 4, dtype=np.uint8)
        mock_read.side_effect = [(red, profile), (nir, profile), (scl, profile)]
        changed = compute_ndvi([0, 0, 5, 5], "2024-06-01", "2024-08-31", geometry=geometry)

        assert changed is not None
        assert changed["mean"] == pytest.approx(0.375)
        assert changed["valid_pixels"] == 8

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_sentinel_rejects_raster_window_that_covers_only_part_of_plot(
        self,
        mock_find,
        mock_read,
    ):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.models.geometry import PolygonGeometry, PolygonPart
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        geometry = PolygonGeometry(
            parts=(PolygonPart(outer=((1, 1), (4, 1), (4, 4), (1, 4), (1, 1))),),
        )
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_bounds(0, 0, 3, 5, 3, 5),
        }
        red = np.full((5, 3), 1000, dtype=np.uint16)
        nir = np.full((5, 3), 3000, dtype=np.uint16)
        scl = np.full((5, 3), 4, dtype=np.uint8)
        mock_read.side_effect = [(red, profile), (nir, profile), (scl, profile)]

        result = compute_ndvi([0, 0, 5, 5], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result == {"available": False, "unavailable_reason": "plot_not_fully_covered"}

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_rejects_raster_window_that_covers_only_part_of_plot(
        self,
        mock_find,
        mock_read,
    ):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.models.geometry import PolygonGeometry, PolygonPart
        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "landsat_partial_plot",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "qa_pixel": "https://example.com/qa.tif",
            "red_scale": 0.0000275,
            "red_offset": -0.2,
            "nir_scale": 0.0000275,
            "nir_offset": -0.2,
            "cloud_cover": 5.0,
            "datetime": "2024-07-15T10:00:00Z",
        }
        geometry = PolygonGeometry(
            parts=(PolygonPart(outer=((1, 1), (4, 1), (4, 4), (1, 4), (1, 1))),),
        )
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_bounds(0, 0, 3, 5, 3, 5),
        }
        bands = np.full((5, 3), 30000, dtype=np.uint16)
        qa = np.zeros((5, 3), dtype=np.uint16)
        mock_read.side_effect = [(bands, profile), (bands, profile), (qa, profile)]

        result = compute_landsat_ndvi(
            [0, 0, 5, 5],
            "2024-06-01",
            "2024-08-31",
            geometry=geometry,
        )

        assert result == {"available": False, "unavailable_reason": "plot_not_fully_covered"}

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_projected_mask_counts_multipart_footprint_not_bbox(self, mock_find, mock_read):
        import numpy as np
        from pyproj import Transformer
        from rasterio.transform import from_bounds

        from treesight.models.geometry import PolygonGeometry, PolygonPart
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 10, 10, 10, 10),
        }
        to_geographic = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

        def ring(bounds):
            x_min, y_min, x_max, y_max = bounds
            return tuple(
                to_geographic.transform(x, y)
                for x, y in (
                    (x_min, y_min),
                    (x_max, y_min),
                    (x_max, y_max),
                    (x_min, y_max),
                    (x_min, y_min),
                )
            )

        geometry = PolygonGeometry(
            parts=(
                PolygonPart(
                    outer=ring((1, 1, 5, 9)),
                    inners=(ring((2, 2, 3, 3)), ring((3, 6, 4, 7))),
                ),
                PolygonPart(outer=ring((7, 6, 9, 10))),
            ),
        )
        red = np.full((10, 10), 1000, dtype=np.uint16)
        nir = np.full((10, 10), 3000, dtype=np.uint16)
        scl = np.full((10, 10), 4, dtype=np.uint8)
        for row, col in ((0, 0), (7, 2), (3, 3), (6, 6)):
            red[row, col], nir[row, col] = 3000, 1000
        mock_read.side_effect = [(red, profile), (nir, profile), (scl, profile)]

        result = compute_ndvi(
            [-1, -1, 1, 1],
            "2024-06-01",
            "2024-08-31",
            geometry=geometry,
        )

        assert result is not None
        assert result["available"] is True
        assert result["geometry_pixels"] == 38
        assert result["total_pixels"] == 38
        assert result["geometry_masked_pixels"] == 62
        assert result["valid_pixels"] == 38
        assert result["mean"] == pytest.approx(0.5)

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_masked_ndvi_geotiffs_drive_plot_only_change_detection(
        self,
        mock_find,
        mock_read,
    ):
        import numpy as np
        from pyproj import Transformer
        from rasterio.transform import from_bounds

        from treesight.models.geometry import PolygonGeometry, PolygonPart
        from treesight.pipeline.enrichment.change_detection import compute_change_map
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 1000, 1000, 10, 10),
        }
        to_geographic = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

        def ring(bounds):
            x_min, y_min, x_max, y_max = bounds
            return tuple(
                to_geographic.transform(x, y)
                for x, y in (
                    (x_min, y_min),
                    (x_max, y_min),
                    (x_max, y_max),
                    (x_min, y_max),
                    (x_min, y_min),
                )
            )

        geometry = PolygonGeometry(
            parts=(
                PolygonPart(
                    outer=ring((100, 100, 900, 900)),
                    inners=(ring((400, 400, 600, 600)),),
                ),
            ),
        )
        scl = np.full((10, 10), 4, dtype=np.uint8)

        def compute(red, nir):
            mock_read.side_effect = [
                (red, profile),
                (nir, profile),
                (scl, profile),
            ]
            return compute_ndvi(
                [0, 0, 1, 1],
                "2024-06-01",
                "2024-08-31",
                geometry=geometry,
            )

        red_baseline = np.full((10, 10), 1000, dtype=np.uint16)
        nir_baseline = np.full((10, 10), 3000, dtype=np.uint16)
        baseline = compute(red_baseline, nir_baseline)

        red_outside = red_baseline.copy()
        nir_outside = nir_baseline.copy()
        red_outside[0, 0] = red_outside[4, 4] = 3000
        nir_outside[0, 0] = nir_outside[4, 4] = 1000
        outside_only = compute(red_outside, nir_outside)

        red_inside = red_baseline.copy()
        nir_inside = nir_baseline.copy()
        red_inside[2, 2] = 3000
        nir_inside[2, 2] = 1000
        inside_clear = compute(red_inside, nir_inside)

        assert baseline is not None
        assert outside_only is not None
        assert inside_clear is not None
        unchanged = compute_change_map(
            baseline["geotiff_bytes"],
            outside_only["geotiff_bytes"],
        )
        clearing = compute_change_map(
            baseline["geotiff_bytes"],
            inside_clear["geotiff_bytes"],
        )

        assert unchanged is not None
        assert unchanged["valid_pixels"] == 60
        assert unchanged["mean_delta"] == 0.0
        assert unchanged["loss_ha"] == 0.0
        assert unchanged["loss_pct"] == 0.0
        assert clearing is not None
        assert clearing["valid_pixels"] == 60
        assert clearing["loss_ha"] == 1.0
        assert clearing["loss_pct"] == pytest.approx(1.7)

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_plot_mask_excludes_outside_and_hole_pixels(self, mock_find, mock_read):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.models.geometry import PolygonGeometry, PolygonPart
        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "landsat_plot_mask",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "qa_pixel": "https://example.com/qa.tif",
            "red_scale": 0.0000275,
            "red_offset": -0.2,
            "nir_scale": 0.0000275,
            "nir_offset": -0.2,
            "cloud_cover": 5.0,
            "datetime": "2024-07-15T10:00:00Z",
        }
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_bounds(0, 0, 5, 5, 5, 5),
        }
        red = np.full((5, 5), 10000, dtype=np.uint16)
        nir = np.full((5, 5), 30000, dtype=np.uint16)
        red[0, 0] = red[2, 2] = 30000
        nir[0, 0] = nir[2, 2] = 10000
        geometry = PolygonGeometry(
            parts=(
                PolygonPart(
                    outer=((1, 1), (4, 1), (4, 4), (1, 4), (1, 1)),
                    inners=(((2, 2), (3, 2), (3, 3), (2, 3), (2, 2)),),
                ),
            ),
        )
        qa = np.zeros((5, 5), dtype=np.uint16)
        qa[1, 1] = 1 << 2
        qa[1, 2] = 2 << 8
        mock_read.side_effect = [(red, profile), (nir, profile), (qa, profile)]

        result = compute_landsat_ndvi([0, 0, 5, 5], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is not None
        assert result["mean"] == pytest.approx(0.7857)
        assert result["qa_applied"] is True
        assert result["valid_pixels"] == 6
        assert result["qa_masked_pixels"] == 2
        assert result["geometry_mask_applied"] is True
        assert result["geometry_mask_method"] == "pixel_center"

    def test_reads_landsat_scale_offset_from_stac_asset_metadata(self):
        from treesight.pipeline.enrichment.ndvi import _asset_reflectance_calibration

        asset = MagicMock()
        asset.extra_fields = {
            "raster:bands": [{"scale": 0.0000275, "offset": -0.2}],
        }

        assert _asset_reflectance_calibration(asset) == (0.0000275, -0.2)

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_qa_read_failure_is_unavailable(self, mock_find, mock_read):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "landsat_qa_failure",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "qa_pixel": "https://example.com/qa.tif",
            "red_scale": 0.0000275,
            "red_offset": -0.2,
            "nir_scale": 0.0000275,
            "nir_offset": -0.2,
            "cloud_cover": 5.0,
            "datetime": "2024-07-15T10:00:00Z",
        }
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_bounds(0, 0, 2, 2, 2, 2),
        }
        data = np.full((2, 2), 20000, dtype=np.uint16)
        mock_read.side_effect = [(data, profile), (data, profile), OSError("QA unavailable")]

        result = compute_landsat_ndvi(
            [0, 0, 2, 2],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result == {"available": False, "unavailable_reason": "qa_mask_unavailable"}

    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_missing_qa_and_calibration_are_unavailable(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "landsat_missing_qa",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "cloud_cover": 5.0,
            "datetime": "2024-07-15T10:00:00Z",
        }

        result = compute_landsat_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result == {"available": False, "unavailable_reason": "qa_mask_unavailable"}

    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_missing_reflectance_calibration_is_unavailable(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "landsat_missing_calibration",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "qa_pixel": "https://example.com/qa.tif",
            "cloud_cover": 5.0,
            "datetime": "2024-07-15T10:00:00Z",
        }

        result = compute_landsat_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result == {
            "available": False,
            "unavailable_reason": "reflectance_calibration_unavailable",
        }

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_handles_exception_gracefully(self, mock_find, mock_read):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture("S2A_err", with_scl=True)
        mock_read.side_effect = Exception("COG read timeout")

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )
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
# Tests for categorical mask alignment
# ---------------------------------------------------------------------------


class TestResampleCategorical:
    def test_reprojects_to_target_grid_using_transforms(self):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import _resample_categorical

        source = np.array([[4, 9], [6, 5]], dtype=np.uint8)
        source_profile = {
            "crs": "EPSG:3857",
            "transform": from_bounds(1, 1, 5, 5, 2, 2),
        }
        target_profile = {
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 5, 5, 5, 5),
        }

        result = _resample_categorical(
            source,
            source_profile,
            target_profile,
            (5, 5),
            source_nodata=0,
        )

        assert result.shape == (5, 5)
        assert result[0, 1] == 4
        assert result[0, 3] == 9
        assert result[4, 0] == 0


# ---------------------------------------------------------------------------
# Tests for SCL masking in compute_ndvi
# ---------------------------------------------------------------------------


class TestComputeNdviWithScl:
    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scl_dark_area_is_not_counted_as_clear_surface(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        band_profile = _band_profile(4, 4)
        scl_profile = _band_profile(2, 2)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        scl = np.full((2, 2), 2, dtype=np.uint8)
        mock_read.side_effect = [
            (red, band_profile),
            (nir, band_profile),
            (scl, scl_profile),
        ]

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result is not None
        assert result["available"] is False
        assert result["unavailable_reason"] == "insufficient_in_plot_pixels"
        assert result["valid_pixels"] == 0

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

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

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

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result == {
            "available": False,
            "unavailable_reason": "cloud_mask_unavailable",
        }

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

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result == {
            "available": False,
            "unavailable_reason": "cloud_mask_unavailable",
        }

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scl_masks_all_pixels_returns_unavailable(self, mock_find, mock_read):
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

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )

        assert result is not None
        assert result["available"] is False
        assert result["unavailable_reason"] == "insufficient_in_plot_pixels"
        assert result["valid_pixels"] == 0

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

        result = compute_ndvi(
            [-0.5, 51.4, -0.4, 51.5],
            "2024-06-01",
            "2024-08-31",
            geometry=_test_plot_geometry(),
        )
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

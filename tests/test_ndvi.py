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
        "transform": from_bounds(0, 0, 100, 100, cols, rows),
        "_source_bounds": (0, 0, 100, 100),
    }


def _test_geometry() -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
    }


class TestFindBestS2Scene:
    def test_checks_next_candidate_until_complete_geometry_coverage(self):
        from treesight.pipeline.enrichment.ndvi import _find_best_s2_scene

        geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
        first = MagicMock(
            id="partial",
            assets={
                "B04": MagicMock(href="partial-red"),
                "B08": MagicMock(href="partial-nir"),
                "SCL": MagicMock(href="partial-scl"),
            },
            properties={"eo:cloud_cover": 1.0, "datetime": "2024-01-01", "proj:epsg": 32632},
        )
        second = MagicMock(
            id="complete",
            assets={
                "B04": MagicMock(href="full-red"),
                "B08": MagicMock(href="full-nir"),
                "SCL": MagicMock(href="full-scl"),
            },
            properties={"eo:cloud_cover": 10.0, "datetime": "2024-01-02", "proj:epsg": 32632},
        )
        search = MagicMock()
        search.items.return_value = [first, second]
        catalog = MagicMock()
        catalog.search.return_value = search
        with (
            patch.dict(
                "sys.modules",
                {
                    "planetary_computer": MagicMock(),
                    "pystac_client": MagicMock(Client=MagicMock(open=MagicMock(return_value=catalog))),
                },
            ),
            patch(
                "treesight.pipeline.enrichment.ndvi._cog_asset_covers_geometry",
                side_effect=[False, True, True, True],
            ),
        ):
            result = _find_best_s2_scene([0, 0, 1, 1], "2024-01-01", "2024-12-31", geometry=geometry)

        assert result["scene_id"] == "complete"

    def test_bounds_asset_coverage_checks_when_no_candidate_covers_geometry(self):
        from treesight.constants import MAX_NDVI_SCENE_CANDIDATES
        from treesight.pipeline.enrichment.ndvi import _find_best_s2_scene

        candidates = [
            MagicMock(
                id=f"partial-{index}",
                assets={
                    "B04": MagicMock(href=f"red-{index}"),
                    "B08": MagicMock(href=f"nir-{index}"),
                    "SCL": MagicMock(href=f"scl-{index}"),
                },
                properties={"eo:cloud_cover": 1.0, "datetime": "2024-01-01", "proj:epsg": 32632},
            )
            for index in range(MAX_NDVI_SCENE_CANDIDATES + 5)
        ]
        search = MagicMock()
        search.items.return_value = candidates
        catalog = MagicMock()
        catalog.search.return_value = search
        geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
        coverage = MagicMock(return_value=False)

        with (
            patch.dict(
                "sys.modules",
                {
                    "planetary_computer": MagicMock(),
                    "pystac_client": MagicMock(Client=MagicMock(open=MagicMock(return_value=catalog))),
                },
            ),
            patch("treesight.pipeline.enrichment.ndvi._cog_asset_covers_geometry", coverage),
        ):
            result = _find_best_s2_scene([0, 0, 1, 1], "2024-01-01", "2024-12-31", geometry=geometry)

        assert result is None
        assert coverage.call_count == MAX_NDVI_SCENE_CANDIDATES


class TestComputeNdvi:
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene", return_value=None)
    def test_fourth_positional_argument_remains_max_cloud(self, mock_find):
        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        bbox = [0, 0, 4, 4]
        result = compute_ndvi(bbox, "2024-06-01", "2024-08-31", 10.0, geometry=_test_geometry())

        assert result is None
        mock_find.assert_called_once_with(bbox, "2024-06-01", "2024-08-31", 10.0, geometry=_test_geometry())

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

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        # B04 (Red) = 1000, B08 (NIR) = 3000 → NDVI = (3000-1000)/(3000+1000) = 0.5
        b04 = np.full((10, 10), 1000, dtype=np.uint16)
        b08 = np.full((10, 10), 3000, dtype=np.uint16)
        profile = _band_profile(10, 10)

        mock_read.side_effect = [
            (b04, profile),
            (b08, profile),
            (np.full((2, 2), 4, dtype=np.uint8), _band_profile(2, 2)),
        ]

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
    def test_partial_source_coverage_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        band = np.full((10, 10), 1000, dtype=np.uint16)
        profile = _band_profile(10, 10)
        mock_read.side_effect = [(band, profile), (band * 3, profile)]
        geometry = {
            "type": "Polygon",
            "coordinates": [[[-10, 10], [50, 10], [50, 50], [-10, 50], [-10, 10]]],
        }

        result = compute_ndvi([0, 0, 50, 50], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is None

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

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        # Different-sized arrays (simulating slight alignment difference)
        b04 = np.full((10, 12), 1000, dtype=np.uint16)
        b08 = np.full((11, 10), 3000, dtype=np.uint16)
        mock_read.side_effect = [
            (b04, _band_profile(10, 12)),
            (b08, _band_profile(11, 10)),
            (np.full((2, 2), 4, dtype=np.uint8), _band_profile(2, 2)),
        ]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is not None
        assert result["valid_pixels"] == 120

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_equal_shape_bands_are_aligned_by_transform(self, mock_find, mock_read):
        import numpy as np
        from rasterio.transform import from_origin

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        bounds = (-1, 0, 5, 4)
        red_profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_origin(0, 4, 1, 1),
            "_source_bounds": bounds,
        }
        shifted_nir_profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_origin(1, 4, 1, 1),
            "_source_bounds": bounds,
        }
        scl_profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_origin(0, 4, 2, 2),
            "_source_bounds": bounds,
        }
        mock_read.side_effect = [
            (red, red_profile),
            (nir, shifted_nir_profile),
            (np.full((2, 2), 4, dtype=np.uint8), scl_profile),
        ]
        geometry = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]}

        result = compute_ndvi([0, 0, 4, 4], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is not None
        assert result["total_pixels"] == 16
        assert result["valid_pixels"] == 12

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

    def test_bounds_include_curved_projected_edges(self):
        from pyproj import Transformer

        from treesight.geo import transform_bbox

        bbox = [5.0, 40.0, 20.0, 70.0]
        result = transform_bbox(bbox, "EPSG:4326", "EPSG:32632")
        expected = Transformer.from_crs("EPSG:4326", "EPSG:32632", always_xy=True).transform_bounds(
            *bbox,
            densify_pts=21,
        )

        assert result[0] <= expected[0]
        assert result[1] <= expected[1]
        assert result[2] >= expected[2]
        assert result[3] >= expected[3]

    def test_projected_polygon_edges_are_densified(self):
        from rasterio.transform import from_origin

        from treesight.pipeline.enrichment.ndvi import _project_geometry_to_raster_crs

        geometry = {
            "type": "Polygon",
            "coordinates": [[[5, 40], [20, 40], [20, 70], [5, 70], [5, 40]]],
        }
        projected = _project_geometry_to_raster_crs(
            geometry,
            {"crs": "EPSG:32632", "transform": from_origin(0, 8_000_000, 100, 100)},
        )

        assert len(projected["coordinates"][0]) > len(geometry["coordinates"][0])


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
        from rasterio.transform import from_bounds

        profile = _band_profile(4, 4)
        scl_profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_bounds(0, 0, 100, 100, 2, 2),
            "_source_bounds": (0, 0, 100, 100),
        }

        mock_read.side_effect = [(b04, profile), (b08, profile), (scl, scl_profile)]

        geometry = {"type": "Polygon", "coordinates": [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]]}
        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is not None
        assert result["scl_applied"] is True
        assert result["scl_masked_pixels"] == 4  # top-right 2x2 quadrant masked
        assert result["valid_pixels"] == 12  # 16 total - 4 cloud

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scene_without_scl_is_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        # Scene without SCL key
        mock_find.return_value = _s2_scene_fixture(with_scl=False)

        b04 = np.full((4, 4), 1000, dtype=np.uint16)
        b08 = np.full((4, 4), 3000, dtype=np.uint16)
        profile = _band_profile(4, 4)

        mock_read.side_effect = [(b04, profile), (b08, profile)]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_scl_read_failure_is_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)

        b04 = np.full((4, 4), 1000, dtype=np.uint16)
        b08 = np.full((4, 4), 3000, dtype=np.uint16)
        profile = _band_profile(4, 4)

        # B04 and B08 succeed, SCL read raises an error
        mock_read.side_effect = [(b04, profile), (b08, profile), Exception("SCL read failed")]

        result = compute_ndvi([-0.5, 51.4, -0.4, 51.5], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is None

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
    def test_low_valid_coverage_is_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        scl = np.array([[4, 9], [9, 9]], dtype=np.uint8)
        mock_read.side_effect = [
            (red, _band_profile(4, 4)),
            (nir, _band_profile(4, 4)),
            (scl, _band_profile(2, 2)),
        ]

        result = compute_ndvi([0, 0, 100, 100], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is None

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

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        profile = _band_profile(4, 4)
        mock_read.side_effect = [
            (red, profile),
            (nir, profile),
            (np.full((2, 2), 4, dtype=np.uint8), _band_profile(2, 2)),
        ]
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
        from rasterio.transform import from_bounds

        profile = {
            "driver": "GTiff",
            "crs": "EPSG:4326",
            "transform": from_bounds(0, 0, 20, 20, 2, 2),
            "_source_bounds": (0, 0, 20, 20),
        }
        mock_read.side_effect = [(red, profile), (nir, profile)]
        geometry = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]],
        }

        result = compute_ndvi([0, 0, 20, 20], "2024-06-01", "2024-08-31", geometry=geometry)

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_in_plot_band_nodata_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        red_coverage = np.ones((4, 4), dtype=bool)
        red_coverage[0, :] = False
        profile = _band_profile(4, 4)
        red_profile = {**profile, "_source_valid_mask": red_coverage}
        nir_profile = {**profile, "_source_valid_mask": np.ones((4, 4), dtype=bool)}
        scl_profile = {**_band_profile(2, 2), "_source_valid_mask": np.ones((2, 2), dtype=bool)}
        mock_read.side_effect = [
            (red, red_profile),
            (nir, nir_profile),
            (np.full((2, 2), 4, dtype=np.uint8), scl_profile),
        ]

        result = compute_ndvi([0, 0, 100, 100], "2024-06-01", "2024-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_nir_and_scl_source_masks_must_cover_parcel(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        scl = np.full((2, 2), 4, dtype=np.uint8)
        geometry = _test_geometry()

        for missing_asset in ("nir", "scl"):
            red_profile = {**_band_profile(4, 4), "_source_valid_mask": np.ones((4, 4), dtype=bool)}
            nir_coverage = np.ones((4, 4), dtype=bool)
            scl_coverage = np.ones((2, 2), dtype=bool)
            if missing_asset == "nir":
                nir_coverage[0, :] = False
            else:
                scl_coverage[0, :] = False
            nir_profile = {**_band_profile(4, 4), "_source_valid_mask": nir_coverage}
            scl_profile = {**_band_profile(2, 2), "_source_valid_mask": scl_coverage}
            mock_read.side_effect = [(red, red_profile), (nir, nir_profile), (scl, scl_profile)]

            result = compute_ndvi([0, 0, 100, 100], "2024-06-01", "2024-08-31", geometry=geometry)

            assert result is None, f"Expected incomplete {missing_asset} source mask to be unavailable"

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_s2_scene")
    def test_plot_mask_excludes_outside_and_hole_pixels(self, mock_find, mock_read):
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import compute_ndvi

        mock_find.return_value = _s2_scene_fixture(with_scl=True)
        red = np.full((4, 4), 1000, dtype=np.uint16)
        nir = np.full((4, 4), 3000, dtype=np.uint16)
        red[0, 0], nir[0, 0] = 1000, 19000  # outside the plot
        red[3, 0], nir[3, 0] = 1000, 19000  # inside a plot hole
        red[0, 3], nir[0, 3] = 9000, 11000  # clearing inside the plot
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 4, 4),
            "_source_bounds": (0, 0, 445277.96, 445640.11),
        }
        scl_profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 2, 2),
            "_source_bounds": (0, 0, 445277.96, 445640.11),
        }
        mock_read.side_effect = [
            (red, profile),
            (nir, profile),
            (np.full((2, 2), 4, dtype=np.uint8), scl_profile),
        ]
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
            "_source_bounds": (0, 0, 445277.96, 445640.11),
        }
        scl_profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 2, 2),
            "_source_bounds": (0, 0, 445277.96, 445640.11),
        }
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
        mock_find.assert_called_once_with(bbox, "2015-06-01", "2015-08-31", 12.0, geometry=_test_geometry())

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
    def test_partial_source_coverage_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_partial",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        band = np.full((10, 10), 1000, dtype=np.uint16)
        profile = _band_profile(10, 10)
        mock_read.side_effect = [(band, profile), (band * 3, profile)]
        geometry = {
            "type": "Polygon",
            "coordinates": [[[-10, 10], [50, 10], [50, 50], [-10, 50], [-10, 10]]],
        }

        result = compute_landsat_ndvi([0, 0, 50, 50], "2015-06-01", "2015-08-31", geometry=geometry)

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
            "qa_pixel": "https://example.com/qa.tif",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        red = np.full((4, 4), 10_000, dtype=np.uint16)
        nir = np.full((4, 4), 20_000, dtype=np.uint16)
        red[0, 0], nir[0, 0] = 1000, 19000
        red[2, 1], nir[2, 1] = 1000, 19000
        red[3, 3], nir[3, 3] = 9_000, 11_000
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 4, 4),
            "_source_bounds": (0, 0, 445277.96, 445640.11),
        }
        mock_read.side_effect = [(red, profile), (nir, profile), (np.zeros((4, 4), dtype=np.uint16), profile)]
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
        assert result["mean"] < 0.65
        assert result["valid_pixels"] < 16
        assert result["total_pixels"] == 12
        with rasterio.open(io.BytesIO(result["geotiff_bytes"])) as raster:
            ndvi = raster.read(1)
        assert np.isnan(ndvi[0, 0])
        assert np.isnan(ndvi[2, 1])
        assert np.isclose(ndvi[3, 3], 0.3667, atol=0.01)

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_surface_reflectance_scale_and_offset_are_applied(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_scaled",
            "red": "red",
            "nir": "nir",
            "qa_pixel": "qa",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        profile = _band_profile(4, 4)
        mock_read.side_effect = [
            (np.full((4, 4), 10_000, dtype=np.uint16), profile),
            (np.full((4, 4), 20_000, dtype=np.uint16), profile),
            (np.zeros((4, 4), dtype=np.uint16), profile),
        ]

        result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

        assert result is not None
        assert abs(result["mean"] - ((0.35 - 0.075) / (0.35 + 0.075))) < 0.001

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_out_of_range_ndvi_from_negative_reflectance_is_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_negative_sr",
            "red": "red",
            "nir": "nir",
            "qa_pixel": "qa",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        profile = _band_profile(4, 4)
        mock_read.side_effect = [
            (np.full((4, 4), 7_000, dtype=np.uint16), profile),
            (np.full((4, 4), 20_000, dtype=np.uint16), profile),
            (np.zeros((4, 4), dtype=np.uint16), profile),
        ]

        result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_without_qa_is_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_no_qa",
            "red": "red",
            "nir": "nir",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        profile = _band_profile(4, 4)
        mock_read.side_effect = [
            (np.full((4, 4), 10_000, dtype=np.uint16), profile),
            (np.full((4, 4), 20_000, dtype=np.uint16), profile),
        ]

        result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_qa_read_failure_is_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_qa_error",
            "red": "red",
            "nir": "nir",
            "qa_pixel": "qa",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        profile = _band_profile(4, 4)
        mock_read.side_effect = [
            (np.full((4, 4), 10_000, dtype=np.uint16), profile),
            (np.full((4, 4), 20_000, dtype=np.uint16), profile),
            OSError("QA read failed"),
        ]

        result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_rejects_low_valid_coverage(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import _LANDSAT_QA_INVALID_MASK, compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_sparse",
            "red": "red",
            "nir": "nir",
            "qa_pixel": "qa",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        profile = _band_profile(4, 4)
        qa = np.full((4, 4), _LANDSAT_QA_INVALID_MASK, dtype=np.uint16)
        qa[:2, :2] = 0
        mock_read.side_effect = [
            (np.full((4, 4), 10_000, dtype=np.uint16), profile),
            (np.full((4, 4), 20_000, dtype=np.uint16), profile),
            (qa, profile),
        ]

        result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_qa_masks_cirrus_pixels(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_qa_flags",
            "red": "red",
            "nir": "nir",
            "qa_pixel": "qa",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        profile = _band_profile(4, 4)
        qa = np.zeros((4, 4), dtype=np.uint16)
        qa[0, 0] = 1 << 2
        mock_read.side_effect = [
            (np.full((4, 4), 10_000, dtype=np.uint16), profile),
            (np.full((4, 4), 20_000, dtype=np.uint16), profile),
            (qa, profile),
        ]

        result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

        assert result is not None
        assert result["qa_masked_pixels"] == 1
        assert result["valid_pixels"] == 15

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_landsat_qa_fill_inside_plot_returns_unavailable(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_partial_fill",
            "red": "red",
            "nir": "nir",
            "qa_pixel": "qa",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        coverage = np.ones((4, 4), dtype=bool)
        profile = {**_band_profile(4, 4), "_source_valid_mask": coverage}
        qa = np.zeros((4, 4), dtype=np.uint16)
        qa[0, :] = 1
        mock_read.side_effect = [
            (np.full((4, 4), 10_000, dtype=np.uint16), profile),
            (np.full((4, 4), 20_000, dtype=np.uint16), profile),
            (qa, {**profile, "nodata": None}),
        ]

        result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

        assert result is None

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_red_nir_and_qa_source_masks_must_cover_parcel(self, mock_find, mock_read):
        import numpy as np

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_partial_source_mask",
            "red": "red",
            "nir": "nir",
            "qa_pixel": "qa",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        red = np.full((4, 4), 10_000, dtype=np.uint16)
        nir = np.full((4, 4), 20_000, dtype=np.uint16)
        qa = np.zeros((4, 4), dtype=np.uint16)

        for missing_asset in ("red", "nir", "qa"):
            red_coverage = np.ones((4, 4), dtype=bool)
            nir_coverage = np.ones((4, 4), dtype=bool)
            qa_coverage = np.ones((4, 4), dtype=bool)
            if missing_asset == "red":
                red_coverage[0, :] = False
            elif missing_asset == "nir":
                nir_coverage[0, :] = False
            else:
                qa_coverage[0, :] = False
            red_profile = {**_band_profile(4, 4), "_source_valid_mask": red_coverage}
            nir_profile = {**_band_profile(4, 4), "_source_valid_mask": nir_coverage}
            qa_profile = {**_band_profile(4, 4), "_source_valid_mask": qa_coverage, "nodata": None}
            mock_read.side_effect = [(red, red_profile), (nir, nir_profile), (qa, qa_profile)]

            result = compute_landsat_ndvi([0, 0, 100, 100], "2015-06-01", "2015-08-31", geometry=_test_geometry())

            assert result is None, f"Expected incomplete {missing_asset} source mask to be unavailable"

    @patch("treesight.pipeline.enrichment.ndvi._cog_band_read")
    @patch("treesight.pipeline.enrichment.ndvi._find_best_landsat_scene")
    def test_qa_masked_count_excludes_pixels_outside_plot(self, mock_find, mock_read):
        import numpy as np
        from rasterio.transform import from_bounds

        from treesight.pipeline.enrichment.ndvi import compute_landsat_ndvi

        mock_find.return_value = {
            "scene_id": "LC08_masked",
            "red": "https://example.com/red.tif",
            "nir": "https://example.com/nir.tif",
            "qa_pixel": "https://example.com/qa.tif",
            "cloud_cover": 5.0,
            "datetime": "2015-07-15T10:00:00Z",
        }
        red = np.full((4, 4), 10_000, dtype=np.uint16)
        nir = np.full((4, 4), 20_000, dtype=np.uint16)
        qa = np.array([[1 << 3, 0], [1 << 3, 1 << 3]], dtype=np.uint16)
        profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 4, 4),
            "_source_bounds": (0, 0, 445277.96, 445640.11),
        }
        qa_profile = {
            "driver": "GTiff",
            "crs": "EPSG:3857",
            "transform": from_bounds(0, 0, 445277.96, 445640.11, 2, 2),
            "_source_bounds": (0, 0, 445277.96, 445640.11),
        }
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


def test_cog_band_read_preserves_nodata_coverage_mask(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from treesight.pipeline.enrichment.ndvi import _cog_band_read

    source_path = tmp_path / "nodata-mask.tif"
    data = np.ones((4, 4), dtype=np.uint8)
    data[1, 2] = 0
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 4, 1, 1),
        nodata=0,
    ) as destination:
        destination.write(data, 1)

    _read_data, profile = _cog_band_read(str(source_path), [0, 0, 4, 4])

    assert profile["_source_valid_mask"].shape == (4, 4)
    assert profile["_source_valid_mask"][1, 2] is np.False_
    assert profile["_source_valid_mask"][0, 0] is np.True_


class TestReprojectToGrid:
    def test_continuous_bands_keep_fractional_bilinear_values(self):
        import numpy as np
        from rasterio.transform import from_origin

        from treesight.pipeline.enrichment.ndvi import _reproject_to_grid

        source_profile = {"crs": "EPSG:4326", "transform": from_origin(0, 2, 1, 1)}
        target_profile = {"crs": "EPSG:4326", "transform": from_origin(0.5, 2, 1, 1)}
        source = np.array([[100, 101], [100, 101]], dtype=np.uint16)

        result = _reproject_to_grid(source, source_profile, target_profile, (2, 2), categorical=False)

        assert result.dtype == np.float32
        assert result[0, 0] == 100.5

    def test_qa_nodata_reprojected_outside_source_stays_invalid(self):
        import numpy as np
        from rasterio.transform import from_origin

        from treesight.pipeline.enrichment.ndvi import _reproject_to_grid

        source_profile = {
            "crs": "EPSG:4326",
            "transform": from_origin(0, 2, 1, 1),
            "nodata": 1,
        }
        target_profile = {"crs": "EPSG:4326", "transform": from_origin(1, 2, 1, 1)}
        source = np.array([[0, 1], [0, 0]], dtype=np.uint16)

        result = _reproject_to_grid(
            source,
            source_profile,
            target_profile,
            (2, 2),
            categorical=True,
            destination_nodata=1,
        )

        assert result[0, 0] == 1

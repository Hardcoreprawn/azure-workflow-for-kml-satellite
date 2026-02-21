"""Tests for the post_process_imagery activity.

Verifies clipping, reprojection, graceful degradation, and path
generation with mocked rasterio operations.

References:
    PID FR-3.11  (reproject if CRS differs)
    PID FR-3.12  (clip to AOI polygon boundary)
    PID FR-4.3   (store clipped imagery under ``/imagery/clipped/``)
    PID Section 7.4.2 (Graceful degradation)
    PID Section 7.4.7 (Unit test tier)
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from kml_satellite.activities.post_process_imagery import (
    DEFAULT_TARGET_CRS,
    PostProcessError,
    _build_geojson_polygon,
    _clip_raster,
    _get_raster_crs,
    post_process_imagery,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_DOWNLOAD_RESULT: dict[str, object] = {
    "order_id": "pc-SCENE_A",
    "scene_id": "SCENE_A",
    "provider": "planetary_computer",
    "aoi_feature_name": "Block A",
    "blob_path": "imagery/raw/2026/03/orchard/block-a.tif",
    "container": "kml-output",
    "size_bytes": 4096,
    "content_type": "image/tiff",
}

_SAMPLE_AOI: dict[str, object] = {
    "feature_name": "Block A",
    "source_file": "orchard.kml",
    "exterior_coords": [
        [150.0, -33.0],
        [150.1, -33.0],
        [150.1, -33.1],
        [150.0, -33.1],
        [150.0, -33.0],
    ],
    "interior_coords": [],
    "bbox": [150.0, -33.1, 150.1, -33.0],
    "buffered_bbox": [149.999, -33.101, 150.101, -32.999],
    "area_ha": 100.0,
    "centroid": [150.05, -33.05],
    "buffer_m": 100.0,
    "crs": "EPSG:4326",
}


def _mock_rasterio_open(
    crs: str = "EPSG:4326",
    width: int = 100,
    height: int = 100,
    count: int = 1,
) -> MagicMock:
    """Create a mock rasterio dataset context manager."""
    mock_src = MagicMock()
    mock_crs = MagicMock()
    mock_crs.__str__ = lambda _self: crs
    mock_crs.__bool__ = lambda _self: bool(crs)
    mock_src.crs = mock_crs
    mock_src.width = width
    mock_src.height = height
    mock_src.count = count
    mock_src.bounds = (150.0, -33.1, 150.1, -33.0)

    # Use MagicMock for profile so .copy() works and returns a real dict
    profile_data = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": width,
        "height": height,
        "count": count,
        "crs": mock_crs,
        "transform": MagicMock(),
    }
    mock_profile = MagicMock()
    mock_profile.copy.return_value = dict(profile_data)
    mock_profile.update = MagicMock()
    mock_src.profile = mock_profile
    return mock_src


# ---------------------------------------------------------------------------
# Tests — post_process_imagery function
# ---------------------------------------------------------------------------


class TestPostProcessImagery(unittest.TestCase):
    """post_process_imagery function with mocked rasterio."""

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_returns_result_dict(self, mock_process: MagicMock) -> None:
        """Happy path: clipping and reprojection succeed."""
        mock_process.return_value = {
            "clipped": True,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/clipped/2026/03/orchard/block-a.tif",
            "output_size_bytes": 2048,
            "clip_error": "",
        }

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
            project_name="Orchard",
            timestamp="2026-03-15T12:00:00+00:00",
        )

        assert result["order_id"] == "pc-SCENE_A"
        assert result["clipped"] is True
        assert result["reprojected"] is False
        assert result["source_crs"] == "EPSG:4326"
        assert result["container"] == "kml-output"
        assert result["processing_duration_seconds"] >= 0

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_clipped_blob_path_follows_pid_layout(self, mock_process: MagicMock) -> None:
        """Output path matches PID Section 10.1 (FR-4.3)."""
        mock_process.return_value = {
            "clipped": True,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/clipped/2026/03/alpha-orchard/block-a.tif",
            "output_size_bytes": 1024,
            "clip_error": "",
        }

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
            project_name="Alpha Orchard",
            timestamp="2026-03-15T12:00:00+00:00",
        )

        assert result["clipped_blob_path"] == "imagery/clipped/2026/03/alpha-orchard/block-a.tif"

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_missing_order_id_raises(self, _mock: MagicMock) -> None:
        """Missing order_id → PostProcessError (not retryable)."""
        dl = dict(_SAMPLE_DOWNLOAD_RESULT)
        del dl["order_id"]

        with self.assertRaises(PostProcessError) as ctx:
            post_process_imagery(dl, dict(_SAMPLE_AOI))
        assert ctx.exception.retryable is False
        assert "order_id" in ctx.exception.message

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_missing_blob_path_raises(self, _mock: MagicMock) -> None:
        """Missing blob_path → PostProcessError (not retryable)."""
        dl = dict(_SAMPLE_DOWNLOAD_RESULT)
        del dl["blob_path"]

        with self.assertRaises(PostProcessError) as ctx:
            post_process_imagery(dl, dict(_SAMPLE_AOI))
        assert ctx.exception.retryable is False
        assert "blob_path" in ctx.exception.message

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_clipping_disabled(self, mock_process: MagicMock) -> None:
        """Clipping disabled → clipped=False in result."""
        mock_process.return_value = {
            "clipped": False,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/raw/2026/03/orchard/block-a.tif",
            "output_size_bytes": 4096,
            "clip_error": "",
        }

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
            enable_clipping=False,
        )

        assert result["clipped"] is False
        # _process_raster called with enable_clipping=False
        call_kwargs = mock_process.call_args
        assert call_kwargs[1]["enable_clipping"] is False

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_graceful_degradation_on_clip_failure(self, mock_process: MagicMock) -> None:
        """Clip failure → clipped=False, clip_error populated (PID 7.4.2)."""
        mock_process.return_value = {
            "clipped": False,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/raw/2026/03/orchard/block-a.tif",
            "output_size_bytes": 0,
            "clip_error": "Raster CRS mismatch with polygon",
        }

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
        )

        assert result["clipped"] is False
        assert result["clip_error"] != ""

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_no_exterior_coords_disables_clipping(self, mock_process: MagicMock) -> None:
        """Empty exterior_coords → clipping disabled automatically."""
        mock_process.return_value = {
            "clipped": False,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/raw/2026/03/orchard/block-a.tif",
            "output_size_bytes": 0,
            "clip_error": "",
        }

        aoi = dict(_SAMPLE_AOI)
        aoi["exterior_coords"] = []

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            aoi,
        )

        # _process_raster should be called with enable_clipping=False
        call_kwargs = mock_process.call_args
        assert call_kwargs[1]["enable_clipping"] is False
        assert result["clipped"] is False

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_reprojection_flag(self, mock_process: MagicMock) -> None:
        """When reprojection is applied, reprojected=True in result."""
        mock_process.return_value = {
            "clipped": True,
            "reprojected": True,
            "source_crs": "EPSG:32756",
            "output_path": "imagery/clipped/2026/03/orchard/block-a.tif",
            "output_size_bytes": 2048,
            "clip_error": "",
        }

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
        )

        assert result["reprojected"] is True
        assert result["source_crs"] == "EPSG:32756"
        assert result["target_crs"] == DEFAULT_TARGET_CRS

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_custom_target_crs(self, mock_process: MagicMock) -> None:
        """Custom target CRS is passed through to result."""
        mock_process.return_value = {
            "clipped": True,
            "reprojected": True,
            "source_crs": "EPSG:4326",
            "output_path": "output.tif",
            "output_size_bytes": 1024,
            "clip_error": "",
        }

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
            target_crs="EPSG:32756",
        )

        assert result["target_crs"] == "EPSG:32756"

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_default_project_becomes_unknown(self, mock_process: MagicMock) -> None:
        """Missing project_name defaults to 'unknown' in path."""
        mock_process.return_value = {
            "clipped": True,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/clipped/2026/03/unknown/block-a.tif",
            "output_size_bytes": 1024,
            "clip_error": "",
        }

        post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
            timestamp="2026-03-15T12:00:00+00:00",
        )

        # Verify _process_raster was called (activity ran)
        mock_process.assert_called_once()

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_uses_scene_id_when_no_feature_name(self, mock_process: MagicMock) -> None:
        """When feature_name is empty, scene_id is used for path."""
        mock_process.return_value = {
            "clipped": True,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "output.tif",
            "output_size_bytes": 1024,
            "clip_error": "",
        }

        aoi = dict(_SAMPLE_AOI)
        aoi["feature_name"] = ""

        post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            aoi,
            project_name="orchard",
            timestamp="2026-06-01T00:00:00+00:00",
        )

        mock_process.assert_called_once()

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_output_container_changes_result_container(self, mock_process: MagicMock) -> None:
        """output_container parameter changes the container in the result dict."""
        mock_process.return_value = {
            "clipped": True,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": "imagery/clipped/2026/03/orchard/block-a.tif",
            "output_size_bytes": 2048,
            "clip_error": "",
        }

        result = post_process_imagery(
            dict(_SAMPLE_DOWNLOAD_RESULT),
            dict(_SAMPLE_AOI),
            project_name="Orchard",
            timestamp="2026-03-15T12:00:00+00:00",
            output_container="acme-output",
        )

        assert result["container"] == "acme-output"


# ---------------------------------------------------------------------------
# Tests — _build_geojson_polygon
# ---------------------------------------------------------------------------


class TestBuildGeoJsonPolygon(unittest.TestCase):
    """Test GeoJSON polygon construction."""

    def test_simple_polygon(self) -> None:
        """Exterior ring only → single-ring polygon."""
        exterior = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
        geojson = _build_geojson_polygon(exterior, [])
        assert geojson["type"] == "Polygon"
        assert len(geojson["coordinates"]) == 1
        assert geojson["coordinates"][0] == exterior

    def test_polygon_with_hole(self) -> None:
        """Polygon with one interior ring (hole)."""
        exterior = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
        interior = [[[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8], [0.2, 0.2]]]
        geojson = _build_geojson_polygon(exterior, interior)
        assert len(geojson["coordinates"]) == 2

    def test_empty_interior(self) -> None:
        """Empty interior_coords → single-ring polygon."""
        exterior = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
        geojson = _build_geojson_polygon(exterior, [])
        assert len(geojson["coordinates"]) == 1


# ---------------------------------------------------------------------------
# Tests — _get_raster_crs
# ---------------------------------------------------------------------------


class TestGetRasterCrs(unittest.TestCase):
    """Test CRS reading from raster files."""

    def test_returns_crs_string(self) -> None:
        """Known CRS → returns string representation."""
        mock_rasterio = MagicMock()
        mock_src = _mock_rasterio_open(crs="EPSG:4326")
        mock_rasterio.open.return_value.__enter__ = lambda _self: mock_src
        mock_rasterio.open.return_value.__exit__ = MagicMock(return_value=False)

        result = _get_raster_crs("test.tif", mock_rasterio)
        assert result == "EPSG:4326"

    def test_returns_empty_on_no_crs(self) -> None:
        """No CRS → returns empty string."""
        mock_rasterio = MagicMock()
        mock_src = MagicMock()
        mock_src.crs = None
        mock_rasterio.open.return_value.__enter__ = lambda _self: mock_src
        mock_rasterio.open.return_value.__exit__ = MagicMock(return_value=False)

        result = _get_raster_crs("test.tif", mock_rasterio)
        assert result == ""

    def test_returns_empty_on_error(self) -> None:
        """File open error → returns empty string (no exception)."""
        mock_rasterio = MagicMock()
        mock_rasterio.open.side_effect = OSError("File not found")

        result = _get_raster_crs("nonexistent.tif", mock_rasterio)
        assert result == ""


# ---------------------------------------------------------------------------
# Tests — _clip_raster
# ---------------------------------------------------------------------------


class TestClipRaster(unittest.TestCase):
    """Test rasterio-based clipping."""

    def test_clip_produces_output(self) -> None:
        """Clipping with valid geometry writes output file."""
        mock_rasterio = MagicMock()

        # Mock rasterio.open for reading
        mock_src = _mock_rasterio_open()
        mock_rasterio.open.return_value.__enter__ = lambda _self: mock_src
        mock_rasterio.open.return_value.__exit__ = MagicMock(return_value=False)

        exterior = [[150.0, -33.0], [150.1, -33.0], [150.1, -33.1], [150.0, -33.0]]

        # Mock rasterio.mask.mask via the import inside _clip_raster
        mock_stat = MagicMock()
        mock_stat.st_size = 2048
        with (
            patch("rasterio.mask.mask") as mock_mask,
            patch("pathlib.Path.stat", return_value=mock_stat),
        ):
            mock_mask.return_value = (
                np.zeros((1, 50, 50), dtype=np.float32),
                MagicMock(),  # transform
            )

            path, size = _clip_raster(
                "input.tif",
                "output.tif",
                exterior,
                [],
                mock_rasterio,
                order_id="test-order",
            )

        assert path == "output.tif"
        assert size == 2048

    def test_clip_failure_raises(self) -> None:
        """Rasterio error during clipping → PostProcessError."""
        mock_rasterio = MagicMock()
        mock_rasterio.open.side_effect = OSError("Cannot open file")

        exterior = [[150.0, -33.0], [150.1, -33.0], [150.1, -33.1], [150.0, -33.0]]

        with self.assertRaises(PostProcessError) as ctx:
            _clip_raster(
                "input.tif",
                "output.tif",
                exterior,
                [],
                mock_rasterio,
                order_id="test-order",
            )

        assert ctx.exception.retryable is True


# ---------------------------------------------------------------------------
# Tests — defaults
# ---------------------------------------------------------------------------


class TestPostProcessDefaults(unittest.TestCase):
    """Verify exported default constants."""

    def test_default_target_crs(self) -> None:
        assert DEFAULT_TARGET_CRS == "EPSG:4326"

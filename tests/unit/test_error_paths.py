"""Fault injection tests — error paths and retry semantics. (Issue #15)

Verifies that every documented failure mode in the pipeline produces
the correct exception type, ``retryable`` flag, and structured error
dict.  All tests are entirely offline — no Azure or network calls.

Failure modes under test:
    acquire_imagery:
        - Empty search results → ImageryAcquisitionError(retryable=False)
        - ProviderSearchError(retryable=True) → ImageryAcquisitionError(retryable=True)
        - ProviderSearchError(retryable=False) → ImageryAcquisitionError(retryable=False)
        - ProviderOrderError(retryable=True) → ImageryAcquisitionError(retryable=True)
        - Invalid AOI payload → ImageryAcquisitionError(retryable=False)

    post_process_imagery:
        - Missing order_id → PostProcessError(retryable=False)
        - Missing blob_path → PostProcessError(retryable=False)
        - Clip failure → graceful degradation: clip_error filled,
          clipped=False, clipped_blob_path == source_blob_path

    parse_kml_file:
        - Malformed XML (not-XML file) → KmlParseError
        - Malformed XML (unclosed tags) → KmlParseError
        - Empty KML (no features) → returns [] without raising
        - Point-only KML (no polygons) → returns []

    Exception taxonomy:
        - Every PipelineError subclass exposes to_error_dict()
        - PipelineError.category reflects retryable flag

References:
    PID 7.4.2  (Fail Loudly, Fail Safely)
    Issue #15  (Error handling and retry semantics)
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from kml_satellite.activities.acquire_imagery import (
    ImageryAcquisitionError,
    acquire_imagery,
)
from kml_satellite.activities.parse_kml import (
    KmlParseError,
    parse_kml_file,
)
from kml_satellite.activities.post_process_imagery import (
    PostProcessError,
    post_process_imagery,
)
from kml_satellite.providers.base import (
    ProviderOrderError,
    ProviderSearchError,
)

# ---------------------------------------------------------------------------
# Test data paths
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parents[1] / "data"
_EDGE_CASES = _DATA_DIR / "edge_cases"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_AOI_DICT: dict[str, object] = {
    "feature_name": "Orchard Block A",
    "source_file": "test.kml",
    "feature_index": 0,
    "exterior_coords": [[-120.5, 46.5], [-120.0, 46.5], [-120.0, 46.0], [-120.5, 46.5]],
    "bbox": [-120.5, 46.0, -120.0, 46.5],
    "buffered_bbox": [-120.51, 45.99, -119.99, 46.51],
    "area_ha": 25.0,
    "centroid": [-120.25, 46.25],
}

_VALID_DOWNLOAD_RESULT: dict[str, object] = {
    "order_id": "pc-SCENE_A",
    "scene_id": "SCENE_A",
    "provider": "planetary_computer",
    "aoi_feature_name": "Orchard Block A",
    "blob_path": "imagery/raw/2026/03/orchard/block-a.tif",
    "container": "kml-output",
    "size_bytes": 4096,
    "content_type": "image/tiff",
}

_VALID_RASTERIO_AOI: dict[str, object] = {
    "feature_name": "Orchard Block A",
    "source_file": "test.kml",
    "exterior_coords": [
        [150.0, -33.0],
        [150.1, -33.0],
        [150.1, -33.1],
        [150.0, -33.1],
        [150.0, -33.0],
    ],
    "interior_coords": [],
    "bbox": [150.0, -33.1, 150.1, -33.0],
    "centroid": [150.05, -33.05],
    "area_ha": 100.0,
    "buffered_bbox": [149.999, -33.101, 150.101, -32.999],
    "crs": "EPSG:4326",
}


def _make_search_result(scene_id: str = "SCENE_A") -> MagicMock:
    sr = MagicMock()
    sr.scene_id = scene_id
    sr.cloud_cover_pct = 5.0
    sr.spatial_resolution_m = 10.0
    sr.acquisition_date = datetime(2026, 1, 15, tzinfo=UTC)
    sr.asset_url = "https://fake.blob/visual.tif"
    return sr


def _make_order_id(scene_id: str = "SCENE_A") -> MagicMock:
    oid = MagicMock()
    oid.order_id = f"pc-{scene_id}"
    oid.scene_id = scene_id
    oid.provider = "planetary_computer"
    return oid


# ---------------------------------------------------------------------------
# acquire_imagery — error paths
# ---------------------------------------------------------------------------


class TestAcquireImageryErrorPaths(unittest.TestCase):
    """Fault injection for the acquire_imagery activity."""

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_empty_search_results_raises_not_retryable(self, mock_get_provider: MagicMock) -> None:
        """Empty provider search returns ImageryAcquisitionError(retryable=False)."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = []
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_VALID_AOI_DICT)

        err = ctx.exception
        self.assertFalse(err.retryable, "No-results error must not be retryable")
        self.assertIn("No imagery found", err.message)
        mock_provider.order.assert_not_called()

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_provider_search_error_retryable_propagates(
        self, mock_get_provider: MagicMock
    ) -> None:
        """ProviderSearchError(retryable=True) → ImageryAcquisitionError(retryable=True)."""
        mock_provider = MagicMock()
        mock_provider.search.side_effect = ProviderSearchError(
            "planetary_computer", "rate limited", retryable=True
        )
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_VALID_AOI_DICT)

        self.assertTrue(ctx.exception.retryable)

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_provider_search_error_non_retryable_propagates(
        self, mock_get_provider: MagicMock
    ) -> None:
        """ProviderSearchError(retryable=False) → ImageryAcquisitionError(retryable=False)."""
        mock_provider = MagicMock()
        mock_provider.search.side_effect = ProviderSearchError(
            "planetary_computer", "invalid AOI", retryable=False
        )
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_VALID_AOI_DICT)

        self.assertFalse(ctx.exception.retryable)

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_provider_order_error_retryable_propagates(self, mock_get_provider: MagicMock) -> None:
        """ProviderOrderError(retryable=True) → ImageryAcquisitionError(retryable=True)."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_search_result()]
        mock_provider.order.side_effect = ProviderOrderError(
            "planetary_computer", "order service unavailable", retryable=True
        )
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_VALID_AOI_DICT)

        self.assertTrue(ctx.exception.retryable)

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_provider_order_error_non_retryable_propagates(
        self, mock_get_provider: MagicMock
    ) -> None:
        """ProviderOrderError(retryable=False) → ImageryAcquisitionError(retryable=False)."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_search_result()]
        mock_provider.order.side_effect = ProviderOrderError(
            "planetary_computer", "scene not orderable", retryable=False
        )
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_VALID_AOI_DICT)

        self.assertFalse(ctx.exception.retryable)

    def test_invalid_aoi_payload_raises_not_retryable(self) -> None:
        """Corrupt AOI dict → ImageryAcquisitionError(retryable=False), no provider call."""
        bad_aoi: dict[str, object] = {"not_a_real_key": 999}
        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(bad_aoi)
        self.assertFalse(ctx.exception.retryable)

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_successful_acquisition_returns_expected_keys(
        self, mock_get_provider: MagicMock
    ) -> None:
        """Smoke-test: happy path returns all required dict keys."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_search_result()]
        mock_provider.order.return_value = _make_order_id()
        mock_get_provider.return_value = mock_provider

        result = acquire_imagery(_VALID_AOI_DICT)

        for key in (
            "order_id",
            "scene_id",
            "provider",
            "cloud_cover_pct",
            "acquisition_date",
            "spatial_resolution_m",
            "aoi_feature_name",
        ):
            self.assertIn(key, result, f"Missing key: {key}")


# ---------------------------------------------------------------------------
# post_process_imagery — error paths
# ---------------------------------------------------------------------------


class TestPostProcessImageryErrorPaths(unittest.TestCase):
    """Fault injection for the post_process_imagery activity."""

    def test_missing_order_id_raises_post_process_error(self) -> None:
        """Missing order_id in download_result → PostProcessError(retryable=False)."""
        bad_result = dict(_VALID_DOWNLOAD_RESULT)
        del bad_result["order_id"]

        with self.assertRaises(PostProcessError) as ctx:
            post_process_imagery(bad_result, _VALID_RASTERIO_AOI)

        self.assertFalse(ctx.exception.retryable)
        self.assertIn("order_id", ctx.exception.message.lower())

    def test_empty_order_id_raises_post_process_error(self) -> None:
        """order_id='' → PostProcessError(retryable=False)."""
        bad_result = {**_VALID_DOWNLOAD_RESULT, "order_id": ""}

        with self.assertRaises(PostProcessError) as ctx:
            post_process_imagery(bad_result, _VALID_RASTERIO_AOI)

        self.assertFalse(ctx.exception.retryable)

    def test_missing_blob_path_raises_post_process_error(self) -> None:
        """Missing blob_path → PostProcessError(retryable=False)."""
        bad_result = {**_VALID_DOWNLOAD_RESULT, "blob_path": "", "adapter_blob_path": ""}

        with self.assertRaises(PostProcessError) as ctx:
            post_process_imagery(bad_result, _VALID_RASTERIO_AOI)

        self.assertFalse(ctx.exception.retryable)
        self.assertIn("blob_path", ctx.exception.message.lower())

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_clip_failure_graceful_degradation(self, mock_process: MagicMock) -> None:
        """When _process_raster reports clip failure, output is source path and clip_error is set."""
        source_path = str(_VALID_DOWNLOAD_RESULT["blob_path"])
        mock_process.return_value = {
            "clipped": False,
            "reprojected": False,
            "source_crs": "EPSG:4326",
            "output_path": source_path,
            "output_size_bytes": 0,
            "clip_error": "rasterio window fell outside raster bounds",
        }

        result = post_process_imagery(_VALID_DOWNLOAD_RESULT, _VALID_RASTERIO_AOI)

        self.assertFalse(result["clipped"])
        self.assertNotEqual(result["clip_error"], "")
        self.assertEqual(result["clipped_blob_path"], source_path)

    @patch("kml_satellite.activities.post_process_imagery._process_raster")
    def test_rasterio_unavailable_graceful_degradation(self, mock_process: MagicMock) -> None:
        """rasterio import failure → clip_error set, output falls back to source."""
        source_path = str(_VALID_DOWNLOAD_RESULT["blob_path"])
        mock_process.return_value = {
            "clipped": False,
            "reprojected": False,
            "source_crs": "",
            "output_path": source_path,
            "output_size_bytes": 0,
            "clip_error": "rasterio not available: No module named 'rasterio'",
        }

        result = post_process_imagery(_VALID_DOWNLOAD_RESULT, _VALID_RASTERIO_AOI)

        self.assertFalse(result["clipped"])
        self.assertIn("rasterio", result["clip_error"])
        self.assertEqual(result["clipped_blob_path"], source_path)


# ---------------------------------------------------------------------------
# parse_kml_file — malformed / edge-case files
# ---------------------------------------------------------------------------


class TestParseKmlErrorPaths(unittest.TestCase):
    """Fault injection for parse_kml_file using edge-case KML fixtures."""

    def test_malformed_not_xml_raises_kml_parse_error(self) -> None:
        """File 11 (binary junk) → KmlParseError raised."""
        kml_path = _EDGE_CASES / "11_malformed_not_xml.kml"
        with self.assertRaises(KmlParseError):
            parse_kml_file(kml_path)

    def test_malformed_unclosed_tags_raises_kml_parse_error(self) -> None:
        """File 12 (unclosed XML tags) → KmlParseError raised."""
        kml_path = _EDGE_CASES / "12_malformed_unclosed_tags.kml"
        with self.assertRaises(KmlParseError):
            parse_kml_file(kml_path)

    def test_empty_kml_returns_empty_list(self) -> None:
        """File 13 (valid KML, no features) → empty list, no exception."""
        kml_path = _EDGE_CASES / "13_empty_no_features.kml"
        result = parse_kml_file(kml_path)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_point_only_kml_returns_empty_list(self) -> None:
        """File 14 (point geometries only, no polygons) → empty list."""
        kml_path = _EDGE_CASES / "14_point_only_no_polygons.kml"
        result = parse_kml_file(kml_path)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# Exception taxonomy contract
# ---------------------------------------------------------------------------


class TestExceptionTaxonomy(unittest.TestCase):
    """Verify the PipelineError base contract is satisfied by all leaf types."""

    def _assert_error_dict(self, err: object, expected_stage: str) -> None:
        """Check to_error_dict() returns stable, populated keys."""
        from kml_satellite.core.exceptions import PipelineError

        assert isinstance(err, PipelineError)
        d = err.to_error_dict()
        self.assertIn("category", d)
        self.assertIn("code", d)
        self.assertIn("stage", d)
        self.assertIn("message", d)
        self.assertIn("retryable", d)
        self.assertEqual(d["stage"], expected_stage)

    def test_imagery_acquisition_error_error_dict(self) -> None:
        err = ImageryAcquisitionError("no scenes found", retryable=False)
        self._assert_error_dict(err, "acquire_imagery")

    def test_imagery_acquisition_error_retryable_category(self) -> None:
        retryable = ImageryAcquisitionError("throttled", retryable=True)
        non_retryable = ImageryAcquisitionError("no scenes", retryable=False)
        # The category attribute must reflect the retryable flag deterministically.
        # Retryable errors should be in the 'transient' category family.
        self.assertNotEqual(retryable.category, non_retryable.category)

    def test_post_process_error_error_dict(self) -> None:
        err = PostProcessError("missing order_id", retryable=False)
        self._assert_error_dict(err, "post_process_imagery")

    def test_provider_search_error_is_pipeline_error(self) -> None:
        from kml_satellite.core.exceptions import PipelineError

        err = ProviderSearchError("planetary_computer", "search failed")
        self.assertIsInstance(err, PipelineError)

    def test_provider_order_error_retryable_flag_preserved(self) -> None:
        retryable = ProviderOrderError("pc", "unavailable", retryable=True)
        non_retryable = ProviderOrderError("pc", "invalid scene", retryable=False)
        self.assertTrue(retryable.retryable)
        self.assertFalse(non_retryable.retryable)

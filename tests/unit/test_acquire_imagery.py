"""Tests for the acquire_imagery activity.

Verifies search → select → order flow with mocked provider adapters.
All provider interactions are mocked to avoid real network calls.

References:
    PID FR-3.8  (submit search queries)
    PID FR-3.9  (poll status — tested in orchestrator)
    PID Section 7.4.7 (Unit test tier)
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from kml_satellite.activities.acquire_imagery import (
    ImageryAcquisitionError,
    _build_filters,
    _build_provider_config,
    acquire_imagery,
)
from kml_satellite.models.imagery import (
    ImageryFilters,
    OrderId,
    ProviderConfig,
    SearchResult,
)
from kml_satellite.providers.base import ProviderError, ProviderSearchError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_AOI_DICT: dict[str, object] = {
    "feature_name": "Orchard Block A",
    "source_file": "test.kml",
    "feature_index": 0,
    "exterior_coords": [[-120.5, 46.5], [-120.0, 46.5], [-120.0, 46.0], [-120.5, 46.5]],
    "bbox": [-120.5, 46.0, -120.0, 46.5],
    "buffered_bbox": [-120.51, 45.99, -119.99, 46.51],
    "area_ha": 25.0,
    "centroid": [-120.25, 46.25],
}


def _make_search_result(
    scene_id: str = "SCENE_A",
    cloud_cover: float = 5.0,
    resolution: float = 10.0,
) -> SearchResult:
    return SearchResult(
        scene_id=scene_id,
        provider="planetary_computer",
        acquisition_date=datetime(2026, 1, 15, tzinfo=UTC),
        cloud_cover_pct=cloud_cover,
        spatial_resolution_m=resolution,
        asset_url="https://fake.blob/visual.tif",
    )


def _make_order_id(scene_id: str = "SCENE_A") -> OrderId:
    return OrderId(
        provider="planetary_computer",
        order_id=f"pc-{scene_id}",
        scene_id=scene_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAcquireImagery(unittest.TestCase):
    """acquire_imagery function with mocked provider."""

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_returns_order_info(self, mock_get_provider: MagicMock) -> None:
        """Happy path: search returns results, best is selected, order placed."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [
            _make_search_result("BEST", cloud_cover=2.0),
            _make_search_result("WORSE", cloud_cover=15.0),
        ]
        mock_provider.order.return_value = _make_order_id("BEST")
        mock_get_provider.return_value = mock_provider

        result = acquire_imagery(_SAMPLE_AOI_DICT)

        assert result["order_id"] == "pc-BEST"
        assert result["scene_id"] == "BEST"
        assert result["provider"] == "planetary_computer"
        assert result["cloud_cover_pct"] == 2.0
        assert result["aoi_feature_name"] == "Orchard Block A"

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_selects_best_scene(self, mock_get_provider: MagicMock) -> None:
        """First result (lowest cloud cover) is selected."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [
            _make_search_result("SCENE_A", cloud_cover=5.0),
        ]
        mock_provider.order.return_value = _make_order_id("SCENE_A")
        mock_get_provider.return_value = mock_provider

        result = acquire_imagery(_SAMPLE_AOI_DICT)
        mock_provider.order.assert_called_once_with("SCENE_A")
        assert result["scene_id"] == "SCENE_A"

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_no_results_raises(self, mock_get_provider: MagicMock) -> None:
        """Empty search results → ImageryAcquisitionError."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = []
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_SAMPLE_AOI_DICT)
        assert "No imagery found" in ctx.exception.message
        assert ctx.exception.retryable is False

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_search_error_propagates(self, mock_get_provider: MagicMock) -> None:
        """ProviderSearchError → ImageryAcquisitionError with retryable flag."""
        mock_provider = MagicMock()
        mock_provider.search.side_effect = ProviderSearchError(
            "pc", "STAC timeout", retryable=True
        )
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_SAMPLE_AOI_DICT)
        assert ctx.exception.retryable is True

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_order_error_propagates(self, mock_get_provider: MagicMock) -> None:
        """ProviderError on order → ImageryAcquisitionError."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_search_result()]
        mock_provider.order.side_effect = ProviderError("pc", "Scene unavailable", retryable=False)
        mock_get_provider.return_value = mock_provider

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_SAMPLE_AOI_DICT)
        assert "Order failed" in ctx.exception.message

    def test_invalid_aoi_raises(self) -> None:
        """Malformed AOI dict → ImageryAcquisitionError (not retryable)."""
        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery({"bbox": "not-a-list"})
        assert ctx.exception.retryable is False

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_custom_provider_name(self, mock_get_provider: MagicMock) -> None:
        """Provider name is passed through correctly."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_search_result()]
        mock_provider.order.return_value = _make_order_id()
        mock_get_provider.return_value = mock_provider

        acquire_imagery(_SAMPLE_AOI_DICT, provider_name="skywatch")
        mock_get_provider.assert_called_once()
        assert mock_get_provider.call_args[0][0] == "skywatch"

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_result_has_acquisition_date(self, mock_get_provider: MagicMock) -> None:
        """Result includes ISO 8601 acquisition date."""
        mock_provider = MagicMock()
        mock_provider.search.return_value = [_make_search_result()]
        mock_provider.order.return_value = _make_order_id()
        mock_get_provider.return_value = mock_provider

        result = acquire_imagery(_SAMPLE_AOI_DICT)
        assert "2026-01-15" in result["acquisition_date"]

    @patch("kml_satellite.activities.acquire_imagery.get_provider")
    def test_unknown_provider_raises(self, mock_get_provider: MagicMock) -> None:
        """Unknown provider → ImageryAcquisitionError (not retryable)."""
        mock_get_provider.side_effect = ProviderError("bad", "Unknown provider")

        with self.assertRaises(ImageryAcquisitionError) as ctx:
            acquire_imagery(_SAMPLE_AOI_DICT, provider_name="bad")
        assert ctx.exception.retryable is False


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestBuildProviderConfig(unittest.TestCase):
    """_build_provider_config helper."""

    def test_default_config(self) -> None:
        config = _build_provider_config("pc", None)
        assert isinstance(config, ProviderConfig)
        assert config.name == "pc"

    def test_override_config(self) -> None:
        config = _build_provider_config(
            "pc",
            {"api_base_url": "https://custom", "extra_params": {"k": "v"}},
        )
        assert config.api_base_url == "https://custom"
        assert config.extra_params == {"k": "v"}


class TestBuildFilters(unittest.TestCase):
    """_build_filters helper."""

    def test_default_filters(self) -> None:
        filters = _build_filters(None)
        assert isinstance(filters, ImageryFilters)
        assert filters.max_cloud_cover_pct == 20.0

    def test_override_filters(self) -> None:
        filters = _build_filters(
            {
                "max_cloud_cover_pct": 5.0,
                "date_start": "2025-06-01T00:00:00+00:00",
                "collections": ["naip"],
            }
        )
        assert filters.max_cloud_cover_pct == 5.0
        assert filters.date_start is not None
        assert filters.collections == ["naip"]

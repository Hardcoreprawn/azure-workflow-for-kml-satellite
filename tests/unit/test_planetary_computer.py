"""Tests for the PlanetaryComputerAdapter.

Unit tests mock the ``pystac_client.Client`` and ``httpx.Client``
to avoid real network calls. The contract test subclass runs the
full ``ProviderContractTests`` mixin against a mocked adapter.

References:
    PID FR-3.2  (Planetary Computer adapter)
    PID FR-3.4  (archive search + download)
    PID Section 7.4.7 (Contract test tier)
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx as _httpx  # for raising HTTPError in download tests

from kml_satellite.models.aoi import AOI
from kml_satellite.models.imagery import (
    BlobReference,
    ImageryFilters,
    OrderId,
    OrderState,
    OrderStatus,
    ProviderConfig,
    SearchResult,
)
from kml_satellite.providers.base import (
    ProviderDownloadError,
    ProviderSearchError,
)
from kml_satellite.providers.planetary_computer import (
    PlanetaryComputerAdapter,
    _aoi_to_bbox,
    _BoundedOrderCache,
    _build_blob_path,
    _build_date_range,
    _resolve_best_asset_url,
)
from tests.unit.test_provider_contract import ProviderContractTests

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_YAKIMA_AOI = AOI(
    feature_name="Yakima Valley Orchard Block A",
    source_file="test.kml",
    feature_index=0,
    exterior_coords=[
        (-120.5, 46.5),
        (-120.0, 46.5),
        (-120.0, 46.0),
        (-120.5, 46.0),
        (-120.5, 46.5),
    ],
    bbox=(-120.5, 46.0, -120.0, 46.5),
    buffered_bbox=(-120.51, 45.99, -119.99, 46.51),
    area_ha=25.0,
    centroid=(-120.25, 46.25),
)


def _make_stac_item(
    item_id: str = "S2B_MSIL2A_20260115T183909_R070_T10TEM_20260115T212159",
    cloud_cover: float = 5.2,
    gsd: float = 10.0,
    bbox: list[float] | None = None,
    datetime_str: str = "2026-01-15T18:39:09Z",
    proj_epsg: int = 32610,
    asset_url: str = "https://fake.blob.core/visual.tif",
    asset_key: str = "visual",
    platform: str = "sentinel-2b",
    constellation: str = "sentinel-2",
    collection_id: str = "sentinel-2-l2a",
) -> Any:
    """Create a fake STAC item for testing."""
    if bbox is None:
        bbox = [-120.5, 46.0, -120.0, 46.5]

    asset = SimpleNamespace(href=asset_url)
    item = SimpleNamespace(
        id=item_id,
        properties={
            "datetime": datetime_str,
            "eo:cloud_cover": cloud_cover,
            "gsd": gsd,
            "proj:epsg": proj_epsg,
            "platform": platform,
            "constellation": constellation,
        },
        bbox=bbox,
        assets={asset_key: asset},
        collection_id=collection_id,
    )
    return item


def _make_stac_item_no_datetime(item_id: str = "NAIP_NODATETIME") -> Any:
    """STAC item with no datetime property (should fall back to now)."""
    asset = SimpleNamespace(href="https://fake.blob.core/naip.tif")
    return SimpleNamespace(
        id=item_id,
        properties={"eo:cloud_cover": 0.0, "gsd": 0.6},
        bbox=[-120.5, 46.0, -120.0, 46.5],
        assets={"visual": asset},
        collection_id="naip",
    )


def _make_stac_item_no_assets(item_id: str = "NO_ASSETS") -> Any:
    """STAC item with no assets (should be skipped)."""
    return SimpleNamespace(
        id=item_id,
        properties={"datetime": "2026-01-15T10:00:00Z"},
        bbox=[-120.5, 46.0, -120.0, 46.5],
        assets={},
        collection_id="sentinel-2-l2a",
    )


def _mock_stac_search(items: list[Any]) -> MagicMock:
    """Create a mock pystac_client.Client whose search always returns *items*.

    The mock returns a fresh iterator on each call so that repeated
    searches (e.g. search + _resolve_asset_url) all succeed.
    """
    mock_client = MagicMock()

    def _make_search(*_args: Any, **_kwargs: Any) -> MagicMock:
        mock_search = MagicMock()
        mock_search.items.return_value = iter(list(items))
        return mock_search

    mock_client.search.side_effect = _make_search
    return mock_client


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestAoiToBbox(unittest.TestCase):
    """_aoi_to_bbox picks buffered_bbox when available."""

    def test_uses_buffered_bbox(self) -> None:
        result = _aoi_to_bbox(_YAKIMA_AOI)
        assert result == (-120.51, 45.99, -119.99, 46.51)

    def test_falls_back_to_bbox(self) -> None:
        aoi = AOI(feature_name="no buffer", bbox=(-1.0, -2.0, 3.0, 4.0))
        result = _aoi_to_bbox(aoi)
        assert result == (-1.0, -2.0, 3.0, 4.0)

    def test_zero_buffered_bbox_falls_back(self) -> None:
        aoi = AOI(
            feature_name="zero buffered",
            bbox=(-1.0, -2.0, 3.0, 4.0),
            buffered_bbox=(0.0, 0.0, 0.0, 0.0),
        )
        result = _aoi_to_bbox(aoi)
        assert result == (-1.0, -2.0, 3.0, 4.0)


class TestBuildDateRange(unittest.TestCase):
    """_build_date_range builds STAC datetime strings."""

    def test_no_dates_returns_none(self) -> None:
        assert _build_date_range(ImageryFilters()) is None

    def test_both_dates(self) -> None:
        f = ImageryFilters(
            date_start=datetime(2025, 1, 1, tzinfo=UTC),
            date_end=datetime(2025, 12, 31, tzinfo=UTC),
        )
        result = _build_date_range(f)
        assert result is not None
        assert "2025-01-01" in result
        assert "2025-12-31" in result
        assert "/" in result

    def test_only_start(self) -> None:
        f = ImageryFilters(date_start=datetime(2025, 6, 1, tzinfo=UTC))
        result = _build_date_range(f)
        assert result is not None
        assert result.endswith("/..")

    def test_only_end(self) -> None:
        f = ImageryFilters(date_end=datetime(2025, 6, 1, tzinfo=UTC))
        result = _build_date_range(f)
        assert result is not None
        assert result.startswith("../")


class TestResolveBestAssetUrl(unittest.TestCase):
    """_resolve_best_asset_url finds the best asset."""

    def test_visual_preferred(self) -> None:
        item = _make_stac_item(asset_key="visual", asset_url="https://v.tif")
        assert _resolve_best_asset_url(item) == "https://v.tif"

    def test_fallback_to_b04(self) -> None:
        asset = SimpleNamespace(href="https://b04.tif")
        item = SimpleNamespace(assets={"B04": asset})
        assert _resolve_best_asset_url(item) == "https://b04.tif"

    def test_fallback_to_first_asset(self) -> None:
        asset = SimpleNamespace(href="https://other.tif")
        item = SimpleNamespace(assets={"some_band": asset})
        assert _resolve_best_asset_url(item) == "https://other.tif"

    def test_no_assets_returns_empty(self) -> None:
        item = SimpleNamespace(assets={})
        assert _resolve_best_asset_url(item) == ""

    def test_none_assets_returns_empty(self) -> None:
        item = SimpleNamespace(assets=None)
        assert _resolve_best_asset_url(item) == ""


class TestBuildBlobPath(unittest.TestCase):
    """_build_blob_path produces deterministic paths."""

    def test_contains_scene_id(self) -> None:
        path = _build_blob_path("MY_SCENE_123")
        assert path == "imagery/raw/MY_SCENE_123.tif"

    def test_idempotent(self) -> None:
        """Same scene_id always produces the same path."""
        assert _build_blob_path("X") == _build_blob_path("X")


# ---------------------------------------------------------------------------
# Adapter search tests
# ---------------------------------------------------------------------------


class TestSearch(unittest.TestCase):
    """PlanetaryComputerAdapter.search() with mocked STAC client."""

    def _make_adapter(self) -> PlanetaryComputerAdapter:
        return PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_returns_results(self, mock_open: MagicMock) -> None:
        mock_open.return_value = _mock_stac_search(
            [
                _make_stac_item("SCENE_A", cloud_cover=10.0),
                _make_stac_item("SCENE_B", cloud_cover=2.0),
            ]
        )

        adapter = self._make_adapter()
        results = adapter.search(_YAKIMA_AOI)

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        # Should be sorted by cloud cover ascending.
        assert results[0].cloud_cover_pct <= results[1].cloud_cover_pct
        assert results[0].scene_id == "SCENE_B"

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_empty_result(self, mock_open: MagicMock) -> None:
        mock_open.return_value = _mock_stac_search([])

        adapter = self._make_adapter()
        results = adapter.search(_YAKIMA_AOI)

        assert results == []

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_with_filters(self, mock_open: MagicMock) -> None:
        mock_open.return_value = _mock_stac_search([_make_stac_item()])

        adapter = self._make_adapter()
        filters = ImageryFilters(
            max_cloud_cover_pct=10.0,
            date_start=datetime(2025, 1, 1, tzinfo=UTC),
            date_end=datetime(2025, 12, 31, tzinfo=UTC),
            collections=["naip"],
        )
        results = adapter.search(_YAKIMA_AOI, filters=filters)

        assert len(results) == 1
        # Verify collection was passed to STAC search.
        mock_client = mock_open.return_value
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["collections"] == ["naip"]
        assert call_kwargs["query"]["eo:cloud_cover"] == {"lte": 10.0}

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_uses_buffered_bbox(self, mock_open: MagicMock) -> None:
        mock_open.return_value = _mock_stac_search([])

        adapter = self._make_adapter()
        adapter.search(_YAKIMA_AOI)

        mock_client = mock_open.return_value
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["bbox"] == (-120.51, 45.99, -119.99, 46.51)

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_no_cloud_filter_at_100(self, mock_open: MagicMock) -> None:
        """Cloud cover filter should not be sent when max is 100%."""
        mock_open.return_value = _mock_stac_search([])

        adapter = self._make_adapter()
        adapter.search(_YAKIMA_AOI, ImageryFilters(max_cloud_cover_pct=100.0))

        mock_client = mock_open.return_value
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["query"] is None

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_api_error_raises_provider_search_error(self, mock_open: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("STAC timeout")
        mock_open.return_value = mock_client

        adapter = self._make_adapter()
        with self.assertRaises(ProviderSearchError) as ctx:
            adapter.search(_YAKIMA_AOI)

        assert ctx.exception.retryable is True
        assert "STAC search failed" in str(ctx.exception)

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_skips_unparseable_items(self, mock_open: MagicMock) -> None:
        """Items that cause parsing errors should be skipped, not crash."""
        bad_item = SimpleNamespace(
            id="BAD_ITEM",
            properties={"datetime": "not-a-date", "eo:cloud_cover": "NaN"},
            bbox="not-a-list",  # Will cause TypeError on float()
            assets={},
            collection_id="sentinel-2-l2a",
        )
        good_item = _make_stac_item("GOOD_ITEM")
        mock_open.return_value = _mock_stac_search([bad_item, good_item])

        adapter = self._make_adapter()
        results = adapter.search(_YAKIMA_AOI)

        assert len(results) == 1
        assert results[0].scene_id == "GOOD_ITEM"

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_no_datetime_falls_back(self, mock_open: MagicMock) -> None:
        """Items without datetime should get a fallback acquisition date."""
        mock_open.return_value = _mock_stac_search([_make_stac_item_no_datetime()])

        adapter = self._make_adapter()
        results = adapter.search(_YAKIMA_AOI)

        assert len(results) == 1
        assert results[0].acquisition_date is not None

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_result_extra_fields(self, mock_open: MagicMock) -> None:
        """SearchResult.extra should include platform and constellation."""
        mock_open.return_value = _mock_stac_search([_make_stac_item()])

        adapter = self._make_adapter()
        results = adapter.search(_YAKIMA_AOI)

        assert results[0].extra["platform"] == "sentinel-2b"
        assert results[0].extra["constellation"] == "sentinel-2"

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_search_result_provider_name(self, mock_open: MagicMock) -> None:
        mock_open.return_value = _mock_stac_search([_make_stac_item()])

        adapter = self._make_adapter()
        results = adapter.search(_YAKIMA_AOI)
        assert results[0].provider == "planetary_computer"


# ---------------------------------------------------------------------------
# Adapter order tests
# ---------------------------------------------------------------------------


class TestOrder(unittest.TestCase):
    """PlanetaryComputerAdapter.order() wraps scene ID."""

    def test_order_returns_order_id(self) -> None:
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        order = adapter.order("SCENE_123")

        assert isinstance(order, OrderId)
        assert order.scene_id == "SCENE_123"
        assert order.provider == "planetary_computer"
        assert "pc-" in order.order_id

    def test_order_id_is_deterministic(self) -> None:
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        o1 = adapter.order("SCENE_A")
        o2 = adapter.order("SCENE_A")
        assert o1.order_id == o2.order_id


# ---------------------------------------------------------------------------
# Adapter poll tests
# ---------------------------------------------------------------------------


class TestPoll(unittest.TestCase):
    """PlanetaryComputerAdapter.poll() returns READY immediately."""

    def test_poll_returns_ready(self) -> None:
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        status = adapter.poll("pc-SCENE_123")

        assert isinstance(status, OrderStatus)
        assert status.state == OrderState.READY
        assert status.progress_pct == 100.0

    def test_poll_any_order_id_returns_ready(self) -> None:
        """STAC has no real order tracking — always ready."""
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        status = adapter.poll("anything")
        assert status.state == OrderState.READY


# ---------------------------------------------------------------------------
# Adapter download tests
# ---------------------------------------------------------------------------


class TestDownload(unittest.TestCase):
    """PlanetaryComputerAdapter.download() with mocked HTTP."""

    def _make_adapter_with_order(self) -> tuple[PlanetaryComputerAdapter, str]:
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        order = adapter.order("SCENE_123")
        return adapter, order.order_id

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    @patch("kml_satellite.providers.planetary_computer.httpx.Client")
    def test_download_returns_blob_reference(
        self, mock_httpx_cls: MagicMock, mock_stac_open: MagicMock
    ) -> None:
        adapter, order_id = self._make_adapter_with_order()

        # Mock STAC item re-fetch.
        mock_stac_open.return_value = _mock_stac_search(
            [_make_stac_item("SCENE_123", asset_url="https://dl.tif")]
        )

        # Mock streaming HTTP download.
        mock_stream_response = MagicMock()
        mock_stream_response.raise_for_status = MagicMock()
        mock_stream_response.iter_bytes.return_value = [b"\x00" * 512, b"\x00" * 512]
        mock_stream_response.__enter__ = MagicMock(return_value=mock_stream_response)
        mock_stream_response.__exit__ = MagicMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.__enter__ = MagicMock(return_value=mock_httpx)
        mock_httpx.__exit__ = MagicMock(return_value=False)
        mock_httpx.stream.return_value = mock_stream_response
        mock_httpx_cls.return_value = mock_httpx

        blob = adapter.download(order_id)

        assert isinstance(blob, BlobReference)
        assert blob.container == "kml-output"
        assert blob.blob_path == "imagery/raw/SCENE_123.tif"
        assert blob.size_bytes == 1024
        assert blob.content_type == "image/tiff"

    def test_download_unknown_order_raises(self) -> None:
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        with self.assertRaises(ProviderDownloadError) as ctx:
            adapter.download("nonexistent-order")
        assert "Unknown order" in str(ctx.exception)

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    def test_download_item_not_found_raises(self, mock_stac_open: MagicMock) -> None:
        adapter, order_id = self._make_adapter_with_order()
        mock_stac_open.return_value = _mock_stac_search([])

        with self.assertRaises(ProviderDownloadError) as ctx:
            adapter.download(order_id)
        assert "not found" in str(ctx.exception)

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    @patch("kml_satellite.providers.planetary_computer.httpx.Client")
    def test_download_http_error_raises(
        self, mock_httpx_cls: MagicMock, mock_stac_open: MagicMock
    ) -> None:
        adapter, order_id = self._make_adapter_with_order()

        mock_stac_open.return_value = _mock_stac_search(
            [_make_stac_item("SCENE_123", asset_url="https://dl.tif")]
        )

        mock_httpx = MagicMock()
        mock_httpx.__enter__ = MagicMock(return_value=mock_httpx)
        mock_httpx.__exit__ = MagicMock(return_value=False)
        mock_httpx.stream.side_effect = _httpx.HTTPError("503 Service Unavailable")
        mock_httpx_cls.return_value = mock_httpx

        with self.assertRaises(ProviderDownloadError) as ctx:
            adapter.download(order_id)
        assert ctx.exception.retryable is True

    @patch("kml_satellite.providers.planetary_computer.pystac_client.Client.open")
    @patch("kml_satellite.providers.planetary_computer.httpx.Client")
    def test_download_custom_container(
        self, mock_httpx_cls: MagicMock, mock_stac_open: MagicMock
    ) -> None:
        """Custom output_container from extra_params is used."""
        adapter = PlanetaryComputerAdapter(
            ProviderConfig(
                name="planetary_computer",
                extra_params={"output_container": "custom-bucket"},
            )
        )
        order = adapter.order("SCENE_X")

        mock_stac_open.return_value = _mock_stac_search(
            [_make_stac_item("SCENE_X", asset_url="https://dl.tif")]
        )
        mock_stream_response = MagicMock()
        mock_stream_response.raise_for_status = MagicMock()
        mock_stream_response.iter_bytes.return_value = [b"\x00" * 512]
        mock_stream_response.__enter__ = MagicMock(return_value=mock_stream_response)
        mock_stream_response.__exit__ = MagicMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.__enter__ = MagicMock(return_value=mock_httpx)
        mock_httpx.__exit__ = MagicMock(return_value=False)
        mock_httpx.stream.return_value = mock_stream_response
        mock_httpx_cls.return_value = mock_httpx

        blob = adapter.download(order.order_id)
        assert blob.container == "custom-bucket"


# ---------------------------------------------------------------------------
# Adapter configuration tests
# ---------------------------------------------------------------------------


class TestAdapterConfig(unittest.TestCase):
    """Configuration handling."""

    def test_default_stac_url(self) -> None:
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        assert "planetarycomputer" in adapter._stac_url

    def test_custom_stac_url(self) -> None:
        adapter = PlanetaryComputerAdapter(
            ProviderConfig(
                name="planetary_computer",
                api_base_url="https://custom.stac/v1",
            )
        )
        assert adapter._stac_url == "https://custom.stac/v1"

    def test_name(self) -> None:
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))
        assert adapter.name == "planetary_computer"


# ---------------------------------------------------------------------------
# Contract test suite — proves the adapter passes the full contract
# ---------------------------------------------------------------------------


class TestPlanetaryComputerContract(ProviderContractTests, unittest.TestCase):
    """Run full ProviderContractTests against a mocked PlanetaryComputerAdapter.

    All STAC and HTTP calls are mocked to avoid network I/O in CI.
    """

    def setUp(self) -> None:
        """Set up patches for STAC client and httpx."""
        self._stac_patcher = patch(
            "kml_satellite.providers.planetary_computer.pystac_client.Client.open"
        )
        self._httpx_patcher = patch("kml_satellite.providers.planetary_computer.httpx.Client")

        mock_stac_open = self._stac_patcher.start()
        mock_httpx_cls = self._httpx_patcher.start()

        # -- STAC mock: always returns two items for any search --
        items = [
            _make_stac_item("CONTRACT_SCENE_A", cloud_cover=5.0),
            _make_stac_item("CONTRACT_SCENE_B", cloud_cover=12.0),
        ]
        mock_stac_open.return_value = _mock_stac_search(items)

        # -- httpx mock: return fake GeoTIFF bytes via streaming --
        mock_stream_response = MagicMock()
        mock_stream_response.raise_for_status = MagicMock()
        mock_stream_response.iter_bytes.return_value = [b"\x00" * 2048]
        mock_stream_response.__enter__ = MagicMock(return_value=mock_stream_response)
        mock_stream_response.__exit__ = MagicMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.__enter__ = MagicMock(return_value=mock_httpx)
        mock_httpx.__exit__ = MagicMock(return_value=False)
        mock_httpx.stream.return_value = mock_stream_response
        mock_httpx_cls.return_value = mock_httpx

    def tearDown(self) -> None:
        self._stac_patcher.stop()
        self._httpx_patcher.stop()

    def create_provider(self) -> PlanetaryComputerAdapter:
        return PlanetaryComputerAdapter(ProviderConfig(name="planetary_computer"))

    def create_test_aoi(self) -> AOI:
        return _YAKIMA_AOI


# ---------------------------------------------------------------------------
# Bounded order cache tests (Issue #56)
# ---------------------------------------------------------------------------


class TestBoundedOrderCache(unittest.TestCase):
    """_BoundedOrderCache eviction and LRU semantics."""

    def test_basic_insert_and_retrieve(self) -> None:
        cache = _BoundedOrderCache(maxsize=4)
        cache["a"] = ("scene_a", "")
        assert "a" in cache
        assert cache["a"] == ("scene_a", "")

    def test_len_tracks_entries(self) -> None:
        cache = _BoundedOrderCache(maxsize=4)
        cache["a"] = ("sa", "")
        cache["b"] = ("sb", "")
        assert len(cache) == 2

    def test_eviction_at_capacity(self) -> None:
        cache = _BoundedOrderCache(maxsize=3)
        cache["a"] = ("sa", "")
        cache["b"] = ("sb", "")
        cache["c"] = ("sc", "")
        assert len(cache) == 3
        assert cache.eviction_count == 0

        cache["d"] = ("sd", "")
        assert len(cache) == 3
        assert "a" not in cache  # oldest evicted
        assert "b" in cache
        assert "d" in cache
        assert cache.eviction_count == 1

    def test_lru_access_promotes_entry(self) -> None:
        cache = _BoundedOrderCache(maxsize=3)
        cache["a"] = ("sa", "")
        cache["b"] = ("sb", "")
        cache["c"] = ("sc", "")

        # Access "a" to promote it to most-recently-used
        _ = cache["a"]

        cache["d"] = ("sd", "")
        # "b" should be evicted (it's now the least-recently-used)
        assert "a" in cache
        assert "b" not in cache
        assert "c" in cache
        assert "d" in cache

    def test_overwrite_promotes_entry(self) -> None:
        cache = _BoundedOrderCache(maxsize=3)
        cache["a"] = ("sa", "")
        cache["b"] = ("sb", "")
        cache["c"] = ("sc", "")

        # Overwrite "a" to promote it
        cache["a"] = ("sa_new", "")

        cache["d"] = ("sd", "")
        # "b" should be evicted
        assert "a" in cache
        assert cache["a"] == ("sa_new", "")
        assert "b" not in cache

    def test_eviction_count_cumulative(self) -> None:
        cache = _BoundedOrderCache(maxsize=2)
        cache["a"] = ("sa", "")
        cache["b"] = ("sb", "")
        cache["c"] = ("sc", "")
        cache["d"] = ("sd", "")
        assert cache.eviction_count == 2

    def test_adapter_uses_bounded_cache(self) -> None:
        """PlanetaryComputerAdapter._orders is a _BoundedOrderCache."""
        adapter = PlanetaryComputerAdapter(ProviderConfig(name="pc"))
        assert isinstance(adapter._orders, _BoundedOrderCache)

    def test_not_in_cache_returns_false(self) -> None:
        cache = _BoundedOrderCache(maxsize=2)
        assert "missing" not in cache

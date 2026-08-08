"""Coverage-hardening tests for treesight/providers/planetary_computer.py.

Phase 1 of issue #886.  All tests mock the STAC/PC API client — no network calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters
from treesight.providers.planetary_computer import (
    COLLECTION_DEFAULT_GSD,
    PlanetaryComputerProvider,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_aoi(name: str = "Test AOI") -> AOI:
    return AOI(
        feature_name=name,
        source_file="test.kml",
        centroid=[-1.5, 51.5],
        bbox=[-1.52, 51.48, -1.48, 51.52],
        buffered_bbox=[-1.55, 51.45, -1.45, 51.55],
        area_ha=10.0,
    )


def _make_stac_item(
    item_id: str = "item-001",
    collection_id: str = "sentinel-2-l2a",
    asset_key: str = "visual",
    cloud_cover: float = 10.0,
    gsd: float | None = None,
    has_asset: bool = True,
    bbox: list[float] | None = None,
    epsg: int | None = 32630,
    platform: str = "sentinel-2b",
) -> MagicMock:
    """Build a minimal mock STAC item."""
    item = MagicMock()
    item.id = item_id
    item.collection_id = collection_id
    item.bbox = bbox or [-1.55, 51.45, -1.45, 51.55]
    asset = MagicMock()
    asset.href = f"https://storage.example.com/{item_id}.tif"
    asset.media_type = "image/tiff"
    item.assets = {asset_key: asset} if has_asset else {}
    props: dict = {"datetime": "2024-06-01T10:00:00Z", "eo:cloud_cover": cloud_cover}
    if gsd is not None:
        props["gsd"] = gsd
    if epsg is not None:
        props["proj:epsg"] = epsg
    if platform:
        props["platform"] = platform
    item.properties = props
    return item


# ---------------------------------------------------------------------------
# _build_datetime_range
# ---------------------------------------------------------------------------


class TestBuildDatetimeRange:
    def test_both_dates(self):
        filters = ImageryFilters(
            date_start=datetime(2024, 1, 1, tzinfo=UTC),
            date_end=datetime(2024, 6, 30, tzinfo=UTC),
        )
        result = PlanetaryComputerProvider._build_datetime_range(filters)
        assert result is not None
        assert "2024-01-01" in result
        assert "2024-06-30" in result
        assert "/" in result

    def test_only_start(self):
        filters = ImageryFilters(date_start=datetime(2024, 1, 1, tzinfo=UTC))
        result = PlanetaryComputerProvider._build_datetime_range(filters)
        assert result is not None
        assert "2024-01-01" in result
        assert result.endswith("/..")

    def test_only_end(self):
        filters = ImageryFilters(date_end=datetime(2024, 6, 30, tzinfo=UTC))
        result = PlanetaryComputerProvider._build_datetime_range(filters)
        assert result is not None
        assert "2024-06-30" in result
        assert result.startswith("../")

    def test_no_dates(self):
        filters = ImageryFilters()
        result = PlanetaryComputerProvider._build_datetime_range(filters)
        assert result is None


# ---------------------------------------------------------------------------
# _build_query
# ---------------------------------------------------------------------------


class TestBuildQuery:
    def test_cloud_filter_added_for_s2(self):
        filters = ImageryFilters(max_cloud_cover_pct=20.0)
        query = PlanetaryComputerProvider._build_query(filters, ["sentinel-2-l2a"])
        assert "eo:cloud_cover" in query
        assert query["eo:cloud_cover"]["lt"] == 20.0

    def test_no_cloud_filter_for_naip(self):
        filters = ImageryFilters(max_cloud_cover_pct=20.0)
        query = PlanetaryComputerProvider._build_query(filters, ["naip"])
        assert query == {}

    def test_cloud_filter_added_when_no_collections_specified(self):
        filters = ImageryFilters(max_cloud_cover_pct=30.0)
        query = PlanetaryComputerProvider._build_query(filters, None)
        assert "eo:cloud_cover" in query

    def test_cloud_filter_when_mixed_collections(self):
        filters = ImageryFilters(max_cloud_cover_pct=15.0)
        query = PlanetaryComputerProvider._build_query(filters, ["naip", "sentinel-2-l2a"])
        assert "eo:cloud_cover" in query


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------


class TestParseDatetime:
    def test_valid_iso_z(self):
        dt = PlanetaryComputerProvider._parse_datetime("2024-06-01T10:00:00Z")
        assert dt.year == 2024
        assert dt.month == 6
        assert dt.tzinfo is not None

    def test_valid_iso_offset(self):
        dt = PlanetaryComputerProvider._parse_datetime("2024-06-01T10:00:00+00:00")
        assert dt.year == 2024

    def test_naive_datetime_gets_utc(self):
        dt = PlanetaryComputerProvider._parse_datetime("2024-06-01T10:00:00")
        assert dt.tzinfo == UTC

    def test_none_returns_now(self):
        before = datetime.now(UTC)
        dt = PlanetaryComputerProvider._parse_datetime(None)
        after = datetime.now(UTC)
        assert before <= dt <= after

    def test_invalid_string_returns_now(self):
        before = datetime.now(UTC)
        dt = PlanetaryComputerProvider._parse_datetime("not-a-date")
        after = datetime.now(UTC)
        assert before <= dt <= after


# ---------------------------------------------------------------------------
# _extract_crs
# ---------------------------------------------------------------------------


class TestExtractCrs:
    def test_epsg_present(self):
        crs = PlanetaryComputerProvider._extract_crs({"proj:epsg": 32630})
        assert crs == "EPSG:32630"

    def test_epsg_missing_falls_back(self):
        crs = PlanetaryComputerProvider._extract_crs({})
        assert crs == "EPSG:4326"


# ---------------------------------------------------------------------------
# _search_collection — mocked catalog
# ---------------------------------------------------------------------------


class TestSearchCollection:
    def _make_provider(self) -> PlanetaryComputerProvider:
        return PlanetaryComputerProvider()

    def test_returns_results_for_items_with_asset(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item = _make_stac_item()
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["sentinel-2-l2a"], aoi, ImageryFilters(), None)

        assert len(results) == 1
        assert results[0].scene_id == "item-001"
        assert results[0].cloud_cover_pct == 10.0

    def test_skips_items_missing_asset(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item = _make_stac_item(has_asset=False)
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["sentinel-2-l2a"], aoi, ImageryFilters(), None)

        assert results == []

    def test_uses_collection_default_gsd_when_omitted(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item = _make_stac_item(collection_id="sentinel-2-l2a", gsd=None)
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["sentinel-2-l2a"], aoi, ImageryFilters(), None)

        assert results[0].spatial_resolution_m == COLLECTION_DEFAULT_GSD["sentinel-2-l2a"]

    def test_uses_item_gsd_when_present(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item = _make_stac_item(collection_id="sentinel-2-l2a", gsd=20.0)
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["sentinel-2-l2a"], aoi, ImageryFilters(), None)

        assert results[0].spatial_resolution_m == 20.0

    def test_falls_back_to_aoi_bbox_when_item_has_no_bbox(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item = _make_stac_item()
        item.bbox = None  # force fallback
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["sentinel-2-l2a"], aoi, ImageryFilters(), None)

        assert results[0].bbox == aoi.buffered_bbox

    def test_sorts_by_cloud_cover_ascending(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item1 = _make_stac_item(item_id="a", cloud_cover=30.0)
        item2 = _make_stac_item(item_id="b", cloud_cover=5.0)
        catalog.search.return_value.items.return_value = [item1, item2]

        results = p._search_collection(catalog, ["sentinel-2-l2a"], aoi, ImageryFilters(), None)

        assert results[0].cloud_cover_pct == 5.0
        assert results[1].cloud_cover_pct == 30.0

    def test_uses_correct_asset_key_for_naip(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item = _make_stac_item(collection_id="naip", asset_key="image")
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["naip"], aoi, ImageryFilters(), None)

        assert len(results) == 1
        assert results[0].extra["collection"] == "naip"

    def test_falls_back_to_default_asset_key_for_unknown_collection(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        # Unknown collection id → default asset key used ("visual")
        item = _make_stac_item(collection_id="unknown-coll", asset_key="visual")
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["unknown-coll"], aoi, ImageryFilters(), None)

        assert len(results) == 1

    def test_no_epsg_gives_wgs84_crs(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        item = _make_stac_item(epsg=None)
        catalog.search.return_value.items.return_value = [item]

        results = p._search_collection(catalog, ["sentinel-2-l2a"], aoi, ImageryFilters(), None)

        assert results[0].crs == "EPSG:4326"

    def test_passes_datetime_range_to_catalog(self):
        p = self._make_provider()
        aoi = _make_aoi()
        catalog = MagicMock()
        catalog.search.return_value.items.return_value = []
        filters = ImageryFilters(
            date_start=datetime(2024, 1, 1, tzinfo=UTC),
            date_end=datetime(2024, 6, 30, tzinfo=UTC),
        )

        p._search_collection(catalog, ["sentinel-2-l2a"], aoi, filters, "2024-01-01/2024-06-30")

        call_kwargs = catalog.search.call_args.kwargs
        assert call_kwargs["datetime"] == "2024-01-01/2024-06-30"


# ---------------------------------------------------------------------------
# search() — full mock of Client.open + planetary_computer
# ---------------------------------------------------------------------------


class TestSearch:
    def _provider(self, **kwargs) -> PlanetaryComputerProvider:
        return PlanetaryComputerProvider(kwargs or None)

    def _mock_catalog(self, items: list) -> MagicMock:
        catalog = MagicMock()
        catalog.search.return_value.items.return_value = items
        return catalog

    def test_stub_mode_raises(self):
        p = PlanetaryComputerProvider({"stub_mode": True})
        aoi = _make_aoi()
        with pytest.raises(NotImplementedError, match="stub_mode"):
            p.search(aoi, ImageryFilters())

    def test_fallback_returns_first_collection_with_results(self):
        p = self._provider(fallback=True)
        aoi = _make_aoi()

        item = _make_stac_item()
        catalog = self._mock_catalog([item])

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.search(aoi, ImageryFilters())

        assert len(results) >= 1

    def test_fallback_skips_empty_collection_and_tries_next(self):
        p = self._provider(fallback=True)
        aoi = _make_aoi()

        item = _make_stac_item(collection_id="sentinel-2-l2a")
        # First collection (naip) returns nothing; second (sentinel-2-l2a) returns item.
        catalog = MagicMock()
        catalog.search.return_value.items.side_effect = [
            iter([]),  # naip → empty
            iter([item]),  # sentinel-2-l2a → result
        ]

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.search(aoi, ImageryFilters())

        assert len(results) >= 1

    def test_fallback_all_empty_returns_empty_list(self):
        p = self._provider(fallback=True, collections=["naip", "sentinel-2-l2a"])
        aoi = _make_aoi()

        catalog = MagicMock()
        catalog.search.return_value.items.return_value = iter([])

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.search(aoi, ImageryFilters())

        assert results == []

    def test_no_fallback_does_single_combined_search(self):
        p = self._provider(fallback=False, collections=["naip", "sentinel-2-l2a"])
        aoi = _make_aoi()

        item = _make_stac_item()
        catalog = self._mock_catalog([item])

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.search(aoi, ImageryFilters())

        # Only one search call made (combined)
        assert catalog.search.call_count == 1
        assert len(results) >= 1

    def test_caller_filters_override_collections(self):
        p = self._provider(fallback=True)
        aoi = _make_aoi()

        item = _make_stac_item(collection_id="naip", asset_key="image")
        catalog = MagicMock()
        catalog.search.return_value.items.return_value = [item]

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            p.search(aoi, ImageryFilters(collections=["naip"]))

        assert catalog.search.call_count == 1


# ---------------------------------------------------------------------------
# download() — stub_mode guard
# ---------------------------------------------------------------------------


class TestDownload:
    def test_stub_mode_raises(self):
        p = PlanetaryComputerProvider({"stub_mode": True})
        with pytest.raises(NotImplementedError, match="stub_mode"):
            p.download("ord-123")

    def test_real_mode_returns_blob_reference(self):
        p = PlanetaryComputerProvider()
        ref = p.download("ord-xyz")
        assert ref.blob_path.endswith("ord-xyz.tif")
        assert ref.content_type == "image/tiff"


# ---------------------------------------------------------------------------
# sign_asset_url
# ---------------------------------------------------------------------------


class TestSignAssetUrl:
    def test_delegates_to_planetary_computer(self):
        p = PlanetaryComputerProvider()
        signed_url = "https://signed.example.com/img.tif"
        with patch("planetary_computer.sign_url", return_value=signed_url) as mock_sign:
            signed = p.sign_asset_url("https://original.example.com/img.tif")
        assert signed == signed_url
        mock_sign.assert_called_once_with("https://original.example.com/img.tif")


# ---------------------------------------------------------------------------
# composite_search
# ---------------------------------------------------------------------------


class TestCompositeSearch:
    def test_stub_mode_raises(self):
        p = PlanetaryComputerProvider({"stub_mode": True})
        aoi = _make_aoi()
        with pytest.raises(NotImplementedError, match="stub_mode"):
            p.composite_search(aoi, ImageryFilters())

    def test_naip_detail_plus_s2_temporal(self):
        p = PlanetaryComputerProvider()
        aoi = _make_aoi()

        naip_item = _make_stac_item(item_id="naip-1", collection_id="naip", asset_key="image")
        s2_item1 = _make_stac_item(item_id="s2-1", collection_id="sentinel-2-l2a")
        s2_item2 = _make_stac_item(item_id="s2-2", collection_id="sentinel-2-l2a", cloud_cover=20.0)

        catalog = MagicMock()
        catalog.search.return_value.items.side_effect = [
            iter([naip_item]),  # naip search
            iter([s2_item1, s2_item2]),  # s2 search
        ]

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.composite_search(aoi, ImageryFilters(), temporal_count=2)

        roles = [r.extra.get("role") for r in results]
        assert "detail" in roles
        assert roles.count("temporal") == 2

    def test_no_naip_coverage_still_returns_s2(self):
        p = PlanetaryComputerProvider()
        aoi = _make_aoi()

        s2_item = _make_stac_item(item_id="s2-1", collection_id="sentinel-2-l2a")

        catalog = MagicMock()
        catalog.search.return_value.items.side_effect = [
            iter([]),  # naip → empty
            iter([s2_item]),  # s2 → result
        ]

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.composite_search(aoi, ImageryFilters(), temporal_count=5)

        assert len(results) == 1
        assert results[0].extra.get("role") == "temporal"

    def test_temporal_count_limits_s2_results(self):
        p = PlanetaryComputerProvider()
        aoi = _make_aoi()

        s2_items = [
            _make_stac_item(item_id=f"s2-{i}", collection_id="sentinel-2-l2a") for i in range(10)
        ]

        catalog = MagicMock()
        catalog.search.return_value.items.side_effect = [
            iter([]),  # naip → empty
            iter(s2_items),  # s2 → many
        ]

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.composite_search(aoi, ImageryFilters(), temporal_count=3)

        assert len(results) == 3
        assert all(r.extra["role"] == "temporal" for r in results)

    def test_naip_role_tagged_as_detail(self):
        p = PlanetaryComputerProvider()
        aoi = _make_aoi()

        naip_item = _make_stac_item(item_id="naip-1", collection_id="naip", asset_key="image")

        catalog = MagicMock()
        catalog.search.return_value.items.side_effect = [
            iter([naip_item]),  # naip
            iter([]),  # s2 empty
        ]

        with (
            patch("pystac_client.Client") as mock_client,
            patch("planetary_computer.sign_inplace"),
        ):
            mock_client.open.return_value = catalog
            results = p.composite_search(aoi, ImageryFilters(), temporal_count=6)

        assert len(results) == 1
        assert results[0].extra["role"] == "detail"


# ---------------------------------------------------------------------------
# order() and poll()
# ---------------------------------------------------------------------------


class TestOrderAndPoll:
    def test_order_returns_prefixed_id(self):
        p = PlanetaryComputerProvider()
        oid = p.order("scene-abc")
        assert oid.startswith("pc-order-scene-abc-")

    def test_poll_always_ready(self):
        p = PlanetaryComputerProvider()
        status = p.poll("any-order-id")
        assert status.state == "ready"
        assert status.is_terminal is True
        assert status.progress_pct == 100.0

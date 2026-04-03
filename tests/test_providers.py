"""Tests for provider registry and Planetary Computer stub (§5)."""

from __future__ import annotations

import pytest

from tests.stub_provider import StubPlanetaryComputerProvider
from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters
from treesight.providers.base import BlobReference, OrderStatus
from treesight.providers.geo_router import (
    GLOBAL_FALLBACK,
    GeoRoutingProvider,
    Region,
    classify_region,
)
from treesight.providers.planetary_computer import PlanetaryComputerProvider
from treesight.providers.registry import clear_provider_cache, get_provider


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_provider_cache()
    yield
    clear_provider_cache()


class TestPlanetaryComputerProvider:
    def test_name(self):
        p = PlanetaryComputerProvider()
        assert p.name == "planetary_computer"

    def test_stub_search_returns_results(self, sample_aoi: AOI):
        p = StubPlanetaryComputerProvider()
        results = p.search(sample_aoi, ImageryFilters())
        assert len(results) >= 1
        assert results[0].provider == "planetary_computer"
        # Default collections put NAIP first
        assert results[0].scene_id.startswith("naip_")

    def test_order_returns_id(self):
        p = PlanetaryComputerProvider()
        oid = p.order("test-scene-123")
        assert oid.startswith("pc-order-test-scene-123-")

    def test_poll_always_ready(self):
        p = PlanetaryComputerProvider()
        status = p.poll("any-order")
        assert isinstance(status, OrderStatus)
        assert status.state == "ready"
        assert status.is_terminal is True

    def test_stub_download_returns_blob_ref(self):
        p = StubPlanetaryComputerProvider()
        ref = p.download("ord-123")
        assert isinstance(ref, BlobReference)
        assert ref.size_bytes > 0
        assert ref.content_type == "image/tiff"

    def test_search_result_fields(self, sample_aoi: AOI):
        p = StubPlanetaryComputerProvider()
        results = p.search(sample_aoi, ImageryFilters())
        r = results[0]
        # NAIP: no cloud cover, US CRS
        assert r.cloud_cover_pct == 0.0
        assert r.crs == "EPSG:26911"
        assert r.extra.get("stub") is True
        assert r.extra.get("collection") == "naip"

    def test_stub_search_s2_only(self, sample_aoi: AOI):
        """Explicit S2-only collections return Sentinel-2 stub results."""
        p = StubPlanetaryComputerProvider({"collections": ["sentinel-2-l2a"]})
        results = p.search(sample_aoi, ImageryFilters())
        assert len(results) >= 1
        assert results[0].scene_id.startswith("S2B_MSIL2A_")
        assert results[0].cloud_cover_pct == 8.5
        assert results[0].crs == "EPSG:32637"

    def test_stub_composite_search(self, sample_aoi: AOI):
        """Composite search returns 1 NAIP detail + N S2 temporal results."""
        p = StubPlanetaryComputerProvider()
        results = p.composite_search(sample_aoi, ImageryFilters(), temporal_count=4)

        assert len(results) == 5  # 1 NAIP + 4 S2
        detail = [r for r in results if r.extra.get("role") == "detail"]
        temporal = [r for r in results if r.extra.get("role") == "temporal"]
        assert len(detail) == 1
        assert len(temporal) == 4
        assert detail[0].extra["collection"] == "naip"
        assert detail[0].spatial_resolution_m == 0.6
        assert all(r.extra["collection"] == "sentinel-2-l2a" for r in temporal)
        assert all(r.spatial_resolution_m == 10.0 for r in temporal)

    def test_stub_composite_temporal_dates_spread(self, sample_aoi: AOI):
        """Composite search temporal results have distinct acquisition dates."""
        p = StubPlanetaryComputerProvider()
        results = p.composite_search(sample_aoi, ImageryFilters(), temporal_count=3)

        temporal = [r for r in results if r.extra.get("role") == "temporal"]
        dates = [r.acquisition_date for r in temporal]
        # All dates should be unique and in descending order (most recent first)
        assert len(set(dates)) == len(dates)
        assert dates == sorted(dates, reverse=True)


class TestProviderRegistry:
    def test_get_planetary_computer(self):
        p = get_provider("planetary_computer")
        assert p.name == "planetary_computer"

    def test_caching(self):
        p1 = get_provider("planetary_computer")
        p2 = get_provider("planetary_computer")
        assert p1 is p2

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown imagery provider"):
            get_provider("nonexistent_provider")

    def test_get_geo_routing(self):
        p = get_provider("geo_routing")
        assert p.name == "geo_routing"


# ---------------------------------------------------------------------------
# Helpers — AOI factories for specific regions
# ---------------------------------------------------------------------------


def _make_aoi(centroid: list[float], name: str = "Test AOI") -> AOI:
    """Build a minimal AOI at the given centroid [lon, lat]."""
    lon, lat = centroid
    return AOI(
        feature_name=name,
        source_file="test.kml",
        centroid=centroid,
        bbox=[lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01],
        buffered_bbox=[lon - 0.02, lat - 0.02, lon + 0.02, lat + 0.02],
        area_ha=5.0,
    )


# AOIs in different regions
US_AOI = _make_aoi([-96.0, 40.0], "Kansas Farm")  # US CONUS
UK_AOI = _make_aoi([-1.5, 51.5], "Wiltshire Field")  # Europe (UK)
BRAZIL_AOI = _make_aoi([-47.9, -15.8], "Brasilia Plot")  # Tropics Americas
CONGO_AOI = _make_aoi([25.0, 0.0], "Congo Basin")  # Tropics Africa
ALASKA_AOI = _make_aoi([-150.0, 64.0], "Alaska Plot")  # US Alaska
HAWAII_AOI = _make_aoi([-155.5, 19.5], "Hawaii Plot")  # US Hawaii
PATAGONIA_AOI = _make_aoi([-70.0, -50.0], "Patagonia Plot")  # Global fallback


# ---------------------------------------------------------------------------
# Region classification
# ---------------------------------------------------------------------------


class TestClassifyRegion:
    def test_us_conus(self):
        region = classify_region(40.0, -96.0)
        assert region.name == "us_conus"
        assert "naip" in region.collections
        assert "landsat-c2-l2" in region.collections

    def test_europe(self):
        region = classify_region(51.5, -1.5)
        assert region.name == "europe"
        assert "sentinel-2-l2a" in region.collections
        assert "landsat-c2-l2" in region.collections
        assert "naip" not in region.collections

    def test_tropics_americas(self):
        region = classify_region(-15.8, -47.9)
        assert region.name == "tropics_americas"
        assert "sentinel-2-l2a" in region.collections
        assert "landsat-c2-l2" in region.collections

    def test_tropics_africa(self):
        region = classify_region(0.0, 25.0)
        assert region.name == "tropics_africa"
        assert "sentinel-2-l2a" in region.collections

    def test_tropics_asia(self):
        region = classify_region(5.0, 110.0)
        assert region.name == "tropics_asia"
        assert "sentinel-2-l2a" in region.collections

    def test_global_fallback(self):
        region = classify_region(-50.0, -70.0)
        assert region.name == "global"
        assert region is GLOBAL_FALLBACK
        assert "landsat-c2-l2" in region.collections

    def test_us_alaska(self):
        region = classify_region(64.0, -150.0)
        assert region.name == "us_alaska"
        assert "landsat-c2-l2" in region.collections

    def test_us_hawaii(self):
        region = classify_region(19.5, -155.5)
        assert region.name == "us_hawaii"
        assert "landsat-c2-l2" in region.collections

    def test_region_contains(self):
        r = Region("test", 10.0, 20.0, 30.0, 40.0, ("sentinel-2-l2a",), 10.0)
        assert r.contains(20.0, 30.0) is True
        assert r.contains(5.0, 30.0) is False


# ---------------------------------------------------------------------------
# GeoRoutingProvider
# ---------------------------------------------------------------------------


class TestGeoRoutingProvider:
    def _make(self, config: dict | None = None) -> GeoRoutingProvider:
        """Create a GeoRoutingProvider backed by StubPlanetaryComputerProvider."""
        p = GeoRoutingProvider(config)
        p.set_provider_class(StubPlanetaryComputerProvider)
        return p

    def test_name(self):
        p = self._make()
        assert p.name == "geo_routing"

    def test_us_search_uses_naip(self):
        """US CONUS AOI should route to NAIP first and get sub-meter results."""
        p = self._make()
        results = p.search(US_AOI, ImageryFilters())
        assert len(results) >= 1
        r = results[0]
        assert r.extra.get("region") == "us_conus"
        assert r.extra.get("routed_by") == "geo_routing"
        assert r.extra.get("collection") == "naip"
        assert r.spatial_resolution_m < 1.0

    def test_europe_search_skips_naip(self):
        """European AOI should get Sentinel-2 directly, not NAIP."""
        p = self._make()
        results = p.search(UK_AOI, ImageryFilters())
        assert len(results) >= 1
        r = results[0]
        assert r.extra.get("region") == "europe"
        assert r.extra.get("collection") == "sentinel-2-l2a"

    def test_tropics_search_uses_sentinel2(self):
        """Tropical AOI should route to Sentinel-2 (best free commercial-use source)."""
        p = self._make()
        results = p.search(BRAZIL_AOI, ImageryFilters())
        assert len(results) >= 1
        r = results[0]
        assert r.extra.get("region") == "tropics_americas"
        assert r.extra.get("collection") == "sentinel-2-l2a"

    def test_tropics_africa_search(self):
        p = self._make()
        results = p.search(CONGO_AOI, ImageryFilters())
        assert len(results) >= 1
        assert results[0].extra.get("region") == "tropics_africa"
        assert results[0].extra.get("collection") == "sentinel-2-l2a"

    def test_global_fallback_search(self):
        """Non-regional AOI falls back to global (Sentinel-2 + Landsat)."""
        p = self._make()
        results = p.search(PATAGONIA_AOI, ImageryFilters())
        assert len(results) >= 1
        assert results[0].extra.get("region") == "global"
        assert results[0].extra.get("collection") == "sentinel-2-l2a"

    def test_order_delegates_to_pc(self):
        p = self._make()
        oid = p.order("test-scene-123")
        assert oid.startswith("pc-order-test-scene-123-")

    def test_poll_delegates_to_pc(self):
        p = self._make()
        status = p.poll("any")
        assert isinstance(status, OrderStatus)
        assert status.state == "ready"

    def test_download_delegates_to_pc(self):
        p = self._make()
        ref = p.download("ord-123")
        assert isinstance(ref, BlobReference)
        assert ref.content_type == "image/tiff"

    def test_composite_search_us(self):
        """Composite search on US CONUS includes NAIP detail."""
        p = self._make()
        results = p.composite_search(US_AOI, ImageryFilters(), temporal_count=3)
        assert len(results) == 4  # 1 NAIP detail + 3 S2 temporal
        detail = [r for r in results if r.extra.get("role") == "detail"]
        assert len(detail) == 1
        assert detail[0].extra.get("region") == "us_conus"
        assert detail[0].extra.get("routed_by") == "geo_routing"

    def test_explicit_collections_override_routing(self):
        """Caller-specified collections override geo-routing."""
        p = self._make()
        filters = ImageryFilters(collections=["sentinel-2-l2a"])
        results = p.search(US_AOI, filters)
        assert len(results) >= 1
        # Even though it's a US AOI, explicit S2 filter should be honoured
        assert results[0].extra.get("collection") == "sentinel-2-l2a"

    def test_results_tagged_with_routing_metadata(self):
        """All results include region and routed_by metadata."""
        p = self._make()
        results = p.search(UK_AOI, ImageryFilters())
        for r in results:
            assert "region" in r.extra
            assert r.extra["routed_by"] == "geo_routing"

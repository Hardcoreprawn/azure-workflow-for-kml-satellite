"""Tests for provider registry and Planetary Computer stub (§5)."""

from __future__ import annotations

import pytest

from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters
from treesight.providers.base import BlobReference, OrderStatus
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
        p = PlanetaryComputerProvider({"stub_mode": True})
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
        p = PlanetaryComputerProvider({"stub_mode": True})
        ref = p.download("ord-123")
        assert isinstance(ref, BlobReference)
        assert ref.size_bytes > 0
        assert ref.content_type == "image/tiff"

    def test_search_result_fields(self, sample_aoi: AOI):
        p = PlanetaryComputerProvider({"stub_mode": True})
        results = p.search(sample_aoi, ImageryFilters())
        r = results[0]
        # NAIP: no cloud cover, US CRS
        assert r.cloud_cover_pct == 0.0
        assert r.crs == "EPSG:26911"
        assert r.extra.get("stub") is True
        assert r.extra.get("collection") == "naip"

    def test_stub_search_s2_only(self, sample_aoi: AOI):
        """Explicit S2-only collections return Sentinel-2 stub results."""
        p = PlanetaryComputerProvider({"stub_mode": True, "collections": ["sentinel-2-l2a"]})
        results = p.search(sample_aoi, ImageryFilters())
        assert len(results) >= 1
        assert results[0].scene_id.startswith("S2B_MSIL2A_")
        assert results[0].cloud_cover_pct == 8.5
        assert results[0].crs == "EPSG:32637"

    def test_stub_composite_search(self, sample_aoi: AOI):
        """Composite search returns 1 NAIP detail + N S2 temporal results."""
        p = PlanetaryComputerProvider({"stub_mode": True})
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
        p = PlanetaryComputerProvider({"stub_mode": True})
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

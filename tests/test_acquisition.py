"""Tests for Phase 2 — acquisition logic (§3.2).

Covers ``acquire_imagery``, ``poll_order``, and ``poll_orders_batch``
using a controllable stub provider.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from treesight.models.aoi import AOI
from treesight.models.imagery import ImageryFilters, SearchResult
from treesight.providers.base import (
    BlobReference,
    ImageryProvider,
    OrderStatus,
    ProviderConfig,
)

# ---------------------------------------------------------------------------
# Stub provider with configurable behaviour
# ---------------------------------------------------------------------------


class _StubProvider(ImageryProvider):
    """Test double that returns canned results controlled by constructor args."""

    def __init__(
        self,
        config: ProviderConfig | None = None,
        *,
        search_results: list[SearchResult] | None = None,
        poll_sequence: list[OrderStatus] | None = None,
    ) -> None:
        super().__init__(config)
        self._search_results = search_results or []
        self._poll_sequence = poll_sequence or [
            OrderStatus(state="ready", is_terminal=True),
        ]
        self._poll_call_count = 0

    @property
    def name(self) -> str:
        return "stub"

    def search(self, aoi: AOI, filters: ImageryFilters) -> list[SearchResult]:
        return self._search_results

    def order(self, scene_id: str) -> str:
        return f"stub-order-{scene_id}"

    def poll(self, order_id: str) -> OrderStatus:
        idx = min(self._poll_call_count, len(self._poll_sequence) - 1)
        self._poll_call_count += 1
        return self._poll_sequence[idx]

    def download(self, order_id: str) -> BlobReference:
        return BlobReference(
            container="kml-output",
            blob_path=f"imagery/raw/stub/{order_id}.tif",
            size_bytes=512,
            content_type="image/tiff",
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 18, 12, 0, 0, tzinfo=UTC)


def _make_search_result(scene_id: str = "SCENE-001") -> SearchResult:
    return SearchResult(
        scene_id=scene_id,
        provider="stub",
        acquisition_date=_NOW,
        cloud_cover_pct=5.0,
        spatial_resolution_m=0.3,
        off_nadir_deg=10.0,
        crs="EPSG:4326",
        bbox=[36.8, -1.31, 36.81, -1.3],
        asset_url="https://stub/SCENE-001.tif",
    )


@pytest.fixture()
def aoi() -> AOI:
    """Minimal AOI for acquisition tests."""
    return AOI(
        feature_name="Test Block",
        source_file="test.kml",
        feature_index=0,
        exterior_coords=[[36.8, -1.3], [36.81, -1.3], [36.81, -1.31], [36.8, -1.3]],
        bbox=[36.8, -1.31, 36.81, -1.3],
        buffered_bbox=[36.79, -1.32, 36.82, -1.29],
        area_ha=12.0,
        centroid=[36.805, -1.305],
        buffer_m=100.0,
        crs="EPSG:4326",
    )


# ---------------------------------------------------------------------------
# acquire_imagery
# ---------------------------------------------------------------------------


class TestAcquireImagery:
    """Tests for ``acquire_imagery``."""

    def test_returns_order_on_match(self, aoi: AOI) -> None:
        """A matching scene produces a valid order dict."""
        from treesight.pipeline.acquisition import acquire_imagery

        provider = _StubProvider(search_results=[_make_search_result()])
        result = acquire_imagery(aoi, provider, ImageryFilters())

        assert result["order_id"] == "stub-order-SCENE-001"
        assert result["scene_id"] == "SCENE-001"
        assert result["provider"] == "stub"
        assert result["aoi_feature_name"] == "Test Block"

    def test_no_results_returns_failed(self, aoi: AOI) -> None:
        """An empty search returns an outcome with state ``failed``."""
        from treesight.pipeline.acquisition import acquire_imagery

        provider = _StubProvider(search_results=[])
        result = acquire_imagery(aoi, provider, ImageryFilters())

        assert result["state"] == "failed"
        assert "No imagery found" in result["error"]

    def test_selects_first_result(self, aoi: AOI) -> None:
        """The provider is expected to return best-match first."""
        from treesight.pipeline.acquisition import acquire_imagery

        results = [
            _make_search_result("BEST"),
            _make_search_result("SECOND"),
        ]
        provider = _StubProvider(search_results=results)
        result = acquire_imagery(aoi, provider, ImageryFilters())

        assert result["scene_id"] == "BEST"


# ---------------------------------------------------------------------------
# poll_order
# ---------------------------------------------------------------------------


class TestPollOrder:
    """Tests for ``poll_order``."""

    def test_immediate_ready(self) -> None:
        """An immediately-ready order returns on first poll."""
        from treesight.pipeline.acquisition import poll_order

        provider = _StubProvider(
            poll_sequence=[OrderStatus(state="ready", is_terminal=True)],
        )
        outcome = poll_order("order-1", provider, poll_interval=0, poll_timeout=5)

        assert outcome.state == "ready"
        assert outcome.poll_count == 1
        assert outcome.order_id == "order-1"

    def test_pending_then_ready(self) -> None:
        """Two pending polls followed by a ready status."""
        from treesight.pipeline.acquisition import poll_order

        provider = _StubProvider(
            poll_sequence=[
                OrderStatus(state="pending", is_terminal=False),
                OrderStatus(state="pending", is_terminal=False),
                OrderStatus(state="ready", is_terminal=True),
            ],
        )
        outcome = poll_order("order-2", provider, poll_interval=0, poll_timeout=10)

        assert outcome.state == "ready"
        assert outcome.poll_count == 3

    def test_timeout(self) -> None:
        """A perpetually-pending provider triggers timeout."""
        from treesight.pipeline.acquisition import poll_order

        provider = _StubProvider(
            poll_sequence=[OrderStatus(state="pending", is_terminal=False)],
        )
        outcome = poll_order(
            "order-3",
            provider,
            poll_interval=0,
            poll_timeout=0,
        )

        assert outcome.state == "acquisition_timeout"
        assert "timed out" in outcome.error.lower()

    def test_failed_terminal_state(self) -> None:
        """A terminal failure is returned immediately."""
        from treesight.pipeline.acquisition import poll_order

        provider = _StubProvider(
            poll_sequence=[
                OrderStatus(state="failed", message="Payment required", is_terminal=True),
            ],
        )
        outcome = poll_order("order-4", provider, poll_interval=0, poll_timeout=10)

        assert outcome.state == "failed"
        assert outcome.poll_count == 1


# ---------------------------------------------------------------------------
# poll_orders_batch
# ---------------------------------------------------------------------------


class TestPollOrdersBatch:
    """Tests for ``poll_orders_batch``."""

    def test_polls_all_orders(self) -> None:
        """All orders in the batch are polled and outcomes returned."""
        from treesight.pipeline.acquisition import poll_orders_batch

        provider = _StubProvider(
            poll_sequence=[OrderStatus(state="ready", is_terminal=True)],
        )
        orders = [
            {"order_id": "o-1", "scene_id": "S-1", "aoi_feature_name": "Block A"},
            {"order_id": "o-2", "scene_id": "S-2", "aoi_feature_name": "Block B"},
        ]
        overrides = {
            "poll_interval_seconds": 0,
            "poll_timeout_seconds": 5,
        }
        results = poll_orders_batch(orders, provider, overrides)

        assert len(results) == 2
        assert results[0].order_id == "o-1"
        assert results[0].scene_id == "S-1"
        assert results[0].aoi_feature_name == "Block A"
        assert results[1].order_id == "o-2"

    def test_empty_batch(self) -> None:
        """An empty order list returns an empty result list."""
        from treesight.pipeline.acquisition import poll_orders_batch

        provider = _StubProvider()
        results = poll_orders_batch([], provider)

        assert results == []


# ---------------------------------------------------------------------------
# acquire_composite
# ---------------------------------------------------------------------------


class TestAcquireComposite:
    """Tests for ``acquire_composite`` with the PC stub provider."""

    def test_returns_detail_and_temporal_orders(self, aoi: AOI) -> None:
        """Composite acquisition returns 1 detail + N temporal orders."""
        from tests.stub_provider import StubPlanetaryComputerProvider
        from treesight.pipeline.acquisition import acquire_composite

        provider = StubPlanetaryComputerProvider()
        orders = acquire_composite(aoi, provider, ImageryFilters(), temporal_count=3)

        detail = [o for o in orders if o.get("role") == "detail"]
        temporal = [o for o in orders if o.get("role") == "temporal"]

        assert len(detail) == 1
        assert len(temporal) == 3
        assert detail[0]["collection"] == "naip"
        assert all(o["collection"] == "sentinel-2-l2a" for o in temporal)
        assert all(o.get("order_id") for o in orders)

    def test_all_orders_have_required_keys(self, aoi: AOI) -> None:
        """Every order dict contains the expected metadata keys."""
        from tests.stub_provider import StubPlanetaryComputerProvider
        from treesight.pipeline.acquisition import acquire_composite

        provider = StubPlanetaryComputerProvider()
        orders = acquire_composite(aoi, provider, ImageryFilters(), temporal_count=2)

        required_keys = {
            "order_id",
            "scene_id",
            "provider",
            "cloud_cover_pct",
            "acquisition_date",
            "spatial_resolution_m",
            "asset_url",
            "aoi_feature_name",
            "role",
            "collection",
        }
        for order in orders:
            missing = required_keys - order.keys()
            assert not missing, f"Missing keys: {missing}"

    def test_fallback_for_non_pc_provider(self, aoi: AOI) -> None:
        """Non-PC providers fall back to regular search (all temporal)."""
        from treesight.pipeline.acquisition import acquire_composite

        results = [_make_search_result("SCENE-A"), _make_search_result("SCENE-B")]
        provider = _StubProvider(search_results=results)
        orders = acquire_composite(aoi, provider, ImageryFilters())

        assert len(orders) == 2
        # Non-PC provider results default to "temporal" role
        assert all(o.get("role") == "temporal" for o in orders)

    def test_no_results_returns_failed(self, aoi: AOI) -> None:
        """Empty search returns a single failed outcome."""
        from treesight.pipeline.acquisition import acquire_composite

        provider = _StubProvider(search_results=[])
        orders = acquire_composite(aoi, provider, ImageryFilters())

        assert len(orders) == 1
        assert orders[0]["state"] == "failed"

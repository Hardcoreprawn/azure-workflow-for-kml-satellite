"""Tests for Phase 2 — acquisition logic (§3.2).

Covers ``acquire_imagery``, ``check_order_status``, and ``acquire_composite``
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
# check_order_status
# ---------------------------------------------------------------------------


class TestCheckOrderStatus:
    """Tests for ``check_order_status`` — single-shot, no loop, no sleep."""

    def test_ready_state_is_terminal(self) -> None:
        """A ready order returns is_terminal=True and state='ready'."""
        from treesight.pipeline.acquisition import check_order_status

        provider = _StubProvider(
            poll_sequence=[OrderStatus(state="ready", is_terminal=True)],
        )
        result = check_order_status("order-1", provider)

        assert result["state"] == "ready"
        assert result["is_terminal"] is True
        assert result["order_id"] == "order-1"
        assert result["provider"] == "stub"
        # error must be a string (not None) — ImageryOutcome.error is `str = ""`,
        # and pydantic validation rejects None when the pipeline summary is built.
        assert result["error"] == ""

    def test_pending_state_is_not_terminal(self) -> None:
        """A pending order returns is_terminal=False."""
        from treesight.pipeline.acquisition import check_order_status

        provider = _StubProvider(
            poll_sequence=[OrderStatus(state="pending", is_terminal=False)],
        )
        result = check_order_status("order-2", provider)

        assert result["state"] == "pending"
        assert result["is_terminal"] is False

    def test_failed_terminal_state(self) -> None:
        """A terminal failure returns state='failed' and is_terminal=True."""
        from treesight.pipeline.acquisition import check_order_status

        provider = _StubProvider(
            poll_sequence=[OrderStatus(state="failed", message="Payment required", is_terminal=True)],
        )
        result = check_order_status("order-3", provider)

        assert result["state"] == "failed"
        assert result["is_terminal"] is True

    def test_unknown_terminal_state_normalized_to_failed(self) -> None:
        """Unknown terminal states are normalized to 'failed'."""
        from treesight.pipeline.acquisition import check_order_status

        provider = _StubProvider(
            poll_sequence=[OrderStatus(state="queued_for_review", is_terminal=True)],
        )
        result = check_order_status("order-4", provider)

        assert result["state"] == "failed"
        assert result["is_terminal"] is True
        assert "queued_for_review" in result["error"]

    def test_no_sleep_or_loop(self) -> None:
        """check_order_status makes exactly one provider.poll call."""
        from treesight.pipeline.acquisition import check_order_status

        provider = _StubProvider(
            poll_sequence=[
                OrderStatus(state="pending", is_terminal=False),
                OrderStatus(state="ready", is_terminal=True),
            ],
        )
        check_order_status("order-5", provider)

        assert provider._poll_call_count == 1


class TestImageryOutcomeStateGuard:
    def test_is_imagery_outcome_state(self) -> None:
        """Guard accepts known literals and rejects unknown provider states."""
        from treesight.pipeline.acquisition import _is_imagery_outcome_state

        assert _is_imagery_outcome_state("ready")
        assert _is_imagery_outcome_state("failed")
        assert not _is_imagery_outcome_state("queued_for_review")


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

"""Contract test suite for imagery provider adapters.

This module defines ``ProviderContractTests`` — an abstract test mixin
that any concrete adapter must pass. It verifies the search → order →
poll → download lifecycle contract without depending on a specific
provider implementation.

Usage — adapter test module::

    class TestMyAdapter(ProviderContractTests, unittest.TestCase):
        def create_provider(self):
            return MyAdapter(ProviderConfig(name="my_adapter"))

        def create_test_aoi(self):
            return AOI(feature_name="test")

Concrete adapter tests (M-2.2+) will subclass this mixin and provide
a real or mocked provider instance.

Additionally, this module includes ``TestFakeAdapterContract`` which runs
the full contract against a minimal in-memory fake adapter to prove the
contract test suite itself works correctly.

References:
    PID Section 7.3  (Provider Adapter Layer)
    PID Section 7.4.7 (Contract test tier)
"""

from __future__ import annotations

import abc
import unittest
from datetime import UTC, datetime

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
    ImageryProvider,
    ProviderError,
)

# ---------------------------------------------------------------------------
# Contract mixin
# ---------------------------------------------------------------------------


class ProviderContractTests(abc.ABC):
    """Abstract mixin verifying the ImageryProvider contract.

    Subclasses must implement ``create_provider()`` and ``create_test_aoi()``
    and mix this with ``unittest.TestCase`` (or similar).

    The mixin is designed so that adapters with instant fulfilment (STAC)
    and those with async polling (SkyWatch) both pass the same tests.
    """

    @abc.abstractmethod
    def create_provider(self) -> ImageryProvider:
        """Return a configured provider instance (real or faked)."""

    @abc.abstractmethod
    def create_test_aoi(self) -> AOI:
        """Return an AOI suitable for the provider's test data."""

    # -- search tests --

    def test_search_returns_list(self) -> None:
        """search() must return a list."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        results = provider.search(aoi)
        self.assertIsInstance(results, list)  # type: ignore[attr-defined]

    def test_search_results_are_search_result(self) -> None:
        """Every element must be a SearchResult."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        results = provider.search(aoi)
        for r in results:
            self.assertIsInstance(r, SearchResult)  # type: ignore[attr-defined]

    def test_search_result_has_required_fields(self) -> None:
        """SearchResult must have non-empty scene_id and provider."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        results = provider.search(aoi)
        if results:
            r = results[0]
            self.assertTrue(r.scene_id, "scene_id must be non-empty")  # type: ignore[attr-defined]
            self.assertTrue(r.provider, "provider must be non-empty")  # type: ignore[attr-defined]
            self.assertIsInstance(r.acquisition_date, datetime)  # type: ignore[attr-defined]

    def test_search_with_filters(self) -> None:
        """search() must accept ImageryFilters without error."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        filters = ImageryFilters(max_cloud_cover_pct=10.0)
        results = provider.search(aoi, filters=filters)
        self.assertIsInstance(results, list)  # type: ignore[attr-defined]

    def test_search_empty_aoi_returns_list(self) -> None:
        """search() on an empty AOI returns a list (possibly empty)."""
        provider = self.create_provider()
        empty_aoi = AOI(feature_name="empty")
        results = provider.search(empty_aoi)
        self.assertIsInstance(results, list)  # type: ignore[attr-defined]

    # -- order tests --

    def test_order_returns_order_id(self) -> None:
        """order() must return an OrderId."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        results = provider.search(aoi)
        if results:
            order = provider.order(results[0].scene_id)
            self.assertIsInstance(order, OrderId)  # type: ignore[attr-defined]
            self.assertTrue(order.order_id, "order_id must be non-empty")  # type: ignore[attr-defined]
            self.assertTrue(order.scene_id, "scene_id must be non-empty")  # type: ignore[attr-defined]

    # -- poll tests --

    def test_poll_returns_order_status(self) -> None:
        """poll() must return an OrderStatus."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        results = provider.search(aoi)
        if results:
            order = provider.order(results[0].scene_id)
            status = provider.poll(order.order_id)
            self.assertIsInstance(status, OrderStatus)  # type: ignore[attr-defined]
            self.assertIsInstance(status.state, OrderState)  # type: ignore[attr-defined]

    def test_poll_state_is_valid_enum(self) -> None:
        """poll() state must be a valid OrderState member."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        results = provider.search(aoi)
        if results:
            order = provider.order(results[0].scene_id)
            status = provider.poll(order.order_id)
            self.assertIn(  # type: ignore[attr-defined]
                status.state,
                list(OrderState),
                f"Got unexpected state: {status.state}",
            )

    # -- download tests --

    def test_download_returns_blob_reference(self) -> None:
        """download() on a READY order must return a BlobReference."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()
        results = provider.search(aoi)
        if results:
            order = provider.order(results[0].scene_id)
            status = provider.poll(order.order_id)
            if status.state == OrderState.READY:
                blob = provider.download(order.order_id)
                self.assertIsInstance(blob, BlobReference)  # type: ignore[attr-defined]
                self.assertTrue(blob.blob_path, "blob_path must be non-empty")  # type: ignore[attr-defined]
                self.assertTrue(blob.container, "container must be non-empty")  # type: ignore[attr-defined]

    # -- lifecycle tests --

    def test_full_lifecycle(self) -> None:
        """search → order → poll → download lifecycle completes."""
        provider = self.create_provider()
        aoi = self.create_test_aoi()

        # 1. Search
        results = provider.search(aoi)
        self.assertIsInstance(results, list)  # type: ignore[attr-defined]
        if not results:
            return  # No coverage — acceptable in contract test

        # 2. Order
        order = provider.order(results[0].scene_id)
        self.assertIsInstance(order, OrderId)  # type: ignore[attr-defined]

        # 3. Poll
        status = provider.poll(order.order_id)
        self.assertIsInstance(status, OrderStatus)  # type: ignore[attr-defined]

        # 4. Download (only if ready)
        if status.state == OrderState.READY:
            blob = provider.download(order.order_id)
            self.assertIsInstance(blob, BlobReference)  # type: ignore[attr-defined]

    # -- provider identity --

    def test_provider_has_name(self) -> None:
        """Provider name must be non-empty."""
        provider = self.create_provider()
        self.assertTrue(provider.name, "Provider name must be non-empty")  # type: ignore[attr-defined]

    def test_provider_has_config(self) -> None:
        """Provider must expose its ProviderConfig."""
        provider = self.create_provider()
        self.assertIsInstance(provider.config, ProviderConfig)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fake adapter for testing the contract tests themselves
# ---------------------------------------------------------------------------


class _FakeAdapter(ImageryProvider):
    """Minimal in-memory adapter that satisfies the full lifecycle.

    Used to verify the contract test mixin itself works correctly.
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._orders: dict[str, str] = {}  # order_id → scene_id

    def search(
        self,
        aoi: AOI,
        filters: ImageryFilters | None = None,  # noqa: ARG002
    ) -> list[SearchResult]:
        if not aoi.feature_name or aoi.feature_name == "empty":
            return []
        return [
            SearchResult(
                scene_id="FAKE_SCENE_001",
                provider=self.name,
                acquisition_date=datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
                cloud_cover_pct=3.5,
                spatial_resolution_m=10.0,
                crs="EPSG:32610",
                bbox=(-120.5, 46.0, -120.0, 46.5),
            ),
            SearchResult(
                scene_id="FAKE_SCENE_002",
                provider=self.name,
                acquisition_date=datetime(2026, 1, 20, 11, 0, 0, tzinfo=UTC),
                cloud_cover_pct=12.0,
                spatial_resolution_m=10.0,
            ),
        ]

    def order(self, scene_id: str) -> OrderId:
        order_id = f"ORD-{scene_id}"
        self._orders[order_id] = scene_id
        return OrderId(provider=self.name, order_id=order_id, scene_id=scene_id)

    def poll(self, order_id: str) -> OrderStatus:
        if order_id not in self._orders:
            return OrderStatus(
                order_id=order_id,
                state=OrderState.FAILED,
                message="Unknown order",
            )
        return OrderStatus(
            order_id=order_id,
            state=OrderState.READY,
            progress_pct=100.0,
            download_url="https://fake.blob.core/imagery.tif",
            updated_at=datetime.now(UTC),
        )

    def download(self, order_id: str) -> BlobReference:
        if order_id not in self._orders:
            msg = f"Order {order_id} not found"
            raise ProviderError(provider=self.name, message=msg)
        return BlobReference(
            container="kml-output",
            blob_path="imagery/raw/2026/01/fake-orchard/fake-scene.tif",
            size_bytes=5_000_000,
        )


# ---------------------------------------------------------------------------
# Run the contract tests against the fake adapter
# ---------------------------------------------------------------------------


class TestFakeAdapterContract(ProviderContractTests, unittest.TestCase):
    """Verify the contract test suite itself by running it against _FakeAdapter."""

    def create_provider(self) -> ImageryProvider:
        return _FakeAdapter(ProviderConfig(name="fake_test"))

    def create_test_aoi(self) -> AOI:
        return AOI(
            feature_name="Test Orchard Block A",
            source_file="test.kml",
            exterior_coords=[
                (-120.5, 46.5),
                (-120.0, 46.5),
                (-120.0, 46.0),
                (-120.5, 46.0),
                (-120.5, 46.5),
            ],
            bbox=(-120.5, 46.0, -120.0, 46.5),
            area_ha=25.0,
            centroid=(-120.25, 46.25),
        )


# ---------------------------------------------------------------------------
# Additional contract edge-case tests
# ---------------------------------------------------------------------------


class TestContractEdgeCases(unittest.TestCase):
    """Edge cases not covered by the contract mixin."""

    def _make_provider(self) -> _FakeAdapter:
        return _FakeAdapter(ProviderConfig(name="fake_edge"))

    def test_search_with_no_results(self) -> None:
        """Provider returns empty list for AOI with no coverage."""
        provider = self._make_provider()
        aoi = AOI(feature_name="empty")
        results = provider.search(aoi)
        assert results == []

    def test_poll_unknown_order_returns_failed(self) -> None:
        """Polling an unknown order returns FAILED state."""
        provider = self._make_provider()
        status = provider.poll("nonexistent-order")
        assert status.state == OrderState.FAILED

    def test_download_unknown_order_raises(self) -> None:
        """Downloading an unknown order raises ProviderError."""
        provider = self._make_provider()
        with self.assertRaises(ProviderError):
            provider.download("nonexistent-order")

    def test_order_preserves_scene_id(self) -> None:
        """OrderId includes the scene_id that was ordered."""
        provider = self._make_provider()
        order = provider.order("MY_SCENE")
        assert order.scene_id == "MY_SCENE"
        assert order.provider == "fake_edge"

    def test_search_respects_filters_type(self) -> None:
        """search() works with explicit filters object."""
        provider = self._make_provider()
        aoi = AOI(feature_name="test", bbox=(-120.5, 46.0, -120.0, 46.5))
        filters = ImageryFilters(
            max_cloud_cover_pct=5.0,
            date_start=datetime(2026, 1, 1, tzinfo=UTC),
            date_end=datetime(2026, 6, 30, tzinfo=UTC),
        )
        results = provider.search(aoi, filters=filters)
        assert len(results) == 2  # Fake always returns 2 for named AOIs

    def test_multiple_orders_tracked_independently(self) -> None:
        """Each order is tracked independently."""
        provider = self._make_provider()
        o1 = provider.order("SCENE_A")
        o2 = provider.order("SCENE_B")
        assert o1.order_id != o2.order_id
        assert provider.poll(o1.order_id).state == OrderState.READY
        assert provider.poll(o2.order_id).state == OrderState.READY

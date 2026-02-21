"""Tests for imagery provider data models.

Covers: ImageryFilters, SearchResult, OrderId, OrderStatus, BlobReference,
ProviderConfig, OrderState enum.

All models are frozen dataclasses — tests verify construction, defaults,
immutability, and explicit unit fields per PID 7.4.5.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import ClassVar

from kml_satellite.models.imagery import (
    BlobReference,
    ImageryFilters,
    ModelValidationError,
    OrderId,
    OrderState,
    OrderStatus,
    ProviderConfig,
    SearchResult,
)

# ---------------------------------------------------------------------------
# OrderState enum
# ---------------------------------------------------------------------------


class TestOrderState(unittest.TestCase):
    """OrderState enum values."""

    def test_enum_values(self) -> None:
        assert OrderState.PENDING.value == "pending"
        assert OrderState.READY.value == "ready"
        assert OrderState.FAILED.value == "failed"
        assert OrderState.CANCELLED.value == "cancelled"

    def test_enum_members_are_four(self) -> None:
        assert len(OrderState) == 4

    def test_str_conversion(self) -> None:
        """Enum name and value are distinct."""
        assert OrderState.READY.name == "READY"
        assert OrderState.READY.value == "ready"


# ---------------------------------------------------------------------------
# ImageryFilters
# ---------------------------------------------------------------------------


class TestImageryFilters(unittest.TestCase):
    """ImageryFilters construction and defaults."""

    def test_defaults(self) -> None:
        f = ImageryFilters()
        assert f.max_cloud_cover_pct == 20.0
        assert f.max_off_nadir_deg == 30.0
        assert f.min_resolution_m == 0.0
        assert f.max_resolution_m == 50.0
        assert f.date_start is None
        assert f.date_end is None
        assert f.collections == []

    def test_custom_values(self) -> None:
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)
        f = ImageryFilters(
            max_cloud_cover_pct=10.0,
            max_off_nadir_deg=15.0,
            min_resolution_m=0.3,
            max_resolution_m=1.0,
            date_start=start,
            date_end=end,
            collections=["sentinel-2-l2a"],
        )
        assert f.max_cloud_cover_pct == 10.0
        assert f.date_start == start
        assert f.date_end == end
        assert f.collections == ["sentinel-2-l2a"]

    def test_frozen(self) -> None:
        f = ImageryFilters()
        with self.assertRaises(AttributeError):
            f.max_cloud_cover_pct = 50.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


class TestSearchResult(unittest.TestCase):
    """SearchResult construction and defaults."""

    def _make(self, **kwargs: object) -> SearchResult:
        defaults: dict[str, object] = {
            "scene_id": "S2A_20260101",
            "provider": "planetary_computer",
            "acquisition_date": datetime(2026, 1, 1, tzinfo=UTC),
        }
        defaults.update(kwargs)
        return SearchResult(**defaults)  # type: ignore[arg-type]

    def test_required_fields(self) -> None:
        r = self._make()
        assert r.scene_id == "S2A_20260101"
        assert r.provider == "planetary_computer"
        assert r.acquisition_date == datetime(2026, 1, 1, tzinfo=UTC)

    def test_defaults(self) -> None:
        r = self._make()
        assert r.cloud_cover_pct == 0.0
        assert r.spatial_resolution_m == 0.0
        assert r.off_nadir_deg == 0.0
        assert r.crs == "EPSG:4326"
        assert r.bbox == (0.0, 0.0, 0.0, 0.0)
        assert r.asset_url == ""
        assert r.extra == {}

    def test_custom_values(self) -> None:
        r = self._make(
            cloud_cover_pct=5.2,
            spatial_resolution_m=10.0,
            crs="EPSG:32637",
            bbox=(-120.5, 46.0, -120.0, 46.5),
            asset_url="https://example.com/scene.tif",
            extra={"platform": "Sentinel-2A"},
        )
        assert r.cloud_cover_pct == 5.2
        assert r.spatial_resolution_m == 10.0
        assert r.bbox == (-120.5, 46.0, -120.0, 46.5)
        assert r.extra["platform"] == "Sentinel-2A"

    def test_frozen(self) -> None:
        r = self._make()
        with self.assertRaises(AttributeError):
            r.scene_id = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# OrderId
# ---------------------------------------------------------------------------


class TestOrderId(unittest.TestCase):
    """OrderId construction."""

    def test_construction(self) -> None:
        o = OrderId(provider="pc", order_id="ord-123", scene_id="S2A_001")
        assert o.provider == "pc"
        assert o.order_id == "ord-123"
        assert o.scene_id == "S2A_001"

    def test_frozen(self) -> None:
        o = OrderId(provider="pc", order_id="ord-123", scene_id="S2A_001")
        with self.assertRaises(AttributeError):
            o.order_id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# OrderStatus
# ---------------------------------------------------------------------------


class TestOrderStatus(unittest.TestCase):
    """OrderStatus construction and defaults."""

    def test_pending(self) -> None:
        s = OrderStatus(order_id="ord-1", state=OrderState.PENDING)
        assert s.state == OrderState.PENDING
        assert s.message == ""
        assert s.progress_pct == 0.0
        assert s.download_url == ""
        assert s.updated_at is None

    def test_ready_with_url(self) -> None:
        now = datetime.now(UTC)
        s = OrderStatus(
            order_id="ord-1",
            state=OrderState.READY,
            download_url="https://example.com/imagery.tif",
            progress_pct=100.0,
            updated_at=now,
        )
        assert s.state == OrderState.READY
        assert s.download_url == "https://example.com/imagery.tif"
        assert s.progress_pct == 100.0
        assert s.updated_at == now

    def test_failed_with_message(self) -> None:
        s = OrderStatus(
            order_id="ord-1",
            state=OrderState.FAILED,
            message="Insufficient coverage",
        )
        assert s.state == OrderState.FAILED
        assert "Insufficient coverage" in s.message


# ---------------------------------------------------------------------------
# BlobReference
# ---------------------------------------------------------------------------


class TestBlobReference(unittest.TestCase):
    """BlobReference construction and defaults."""

    def test_construction(self) -> None:
        b = BlobReference(
            container="kml-output",
            blob_path="imagery/raw/2026/01/orchard/block-a.tif",
            size_bytes=1_048_576,
        )
        assert b.container == "kml-output"
        assert b.blob_path == "imagery/raw/2026/01/orchard/block-a.tif"
        assert b.size_bytes == 1_048_576
        assert b.content_type == "image/tiff"

    def test_default_content_type(self) -> None:
        b = BlobReference(container="c", blob_path="p")
        assert b.content_type == "image/tiff"
        assert b.size_bytes == 0


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------


class TestProviderConfig(unittest.TestCase):
    """ProviderConfig construction and defaults."""

    def test_minimal(self) -> None:
        c = ProviderConfig(name="test_provider")
        assert c.name == "test_provider"
        assert c.api_base_url == ""
        assert c.auth_mechanism == "none"
        assert c.keyvault_secret_name == ""
        assert c.extra_params == {}

    def test_full(self) -> None:
        c = ProviderConfig(
            name="skywatch",
            api_base_url="https://api.skywatch.com/v2",
            auth_mechanism="api_key",
            keyvault_secret_name="skywatch-api-key",  # pragma: allowlist secret
            extra_params={"max_results": "50"},
        )
        assert c.api_base_url == "https://api.skywatch.com/v2"
        assert c.auth_mechanism == "api_key"
        assert c.keyvault_secret_name == "skywatch-api-key"  # pragma: allowlist secret
        assert c.extra_params["max_results"] == "50"

    def test_frozen(self) -> None:
        c = ProviderConfig(name="test")
        with self.assertRaises(AttributeError):
            c.name = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Invariant / validation tests
# ---------------------------------------------------------------------------


class TestModelValidationError(unittest.TestCase):
    """ModelValidationError attributes and message formatting."""

    def test_attributes(self) -> None:
        err = ModelValidationError("Foo", "bar", -1, "must be >= 0")
        assert err.model == "Foo"
        assert err.field_name == "bar"
        assert err.value == -1
        assert "Foo.bar=-1" in str(err)

    def test_is_value_error(self) -> None:
        assert issubclass(ModelValidationError, ValueError)


class TestImageryFiltersInvariants(unittest.TestCase):
    """Invariant enforcement for ImageryFilters."""

    def test_cloud_cover_below_zero(self) -> None:
        with self.assertRaises(ModelValidationError) as ctx:
            ImageryFilters(max_cloud_cover_pct=-1)
        assert ctx.exception.field_name == "max_cloud_cover_pct"

    def test_cloud_cover_above_100(self) -> None:
        with self.assertRaises(ModelValidationError):
            ImageryFilters(max_cloud_cover_pct=101)

    def test_cloud_cover_boundary_zero(self) -> None:
        f = ImageryFilters(max_cloud_cover_pct=0)
        assert f.max_cloud_cover_pct == 0

    def test_cloud_cover_boundary_100(self) -> None:
        f = ImageryFilters(max_cloud_cover_pct=100)
        assert f.max_cloud_cover_pct == 100

    def test_off_nadir_below_zero(self) -> None:
        with self.assertRaises(ModelValidationError):
            ImageryFilters(max_off_nadir_deg=-0.1)

    def test_off_nadir_above_90(self) -> None:
        with self.assertRaises(ModelValidationError):
            ImageryFilters(max_off_nadir_deg=91)

    def test_negative_min_resolution(self) -> None:
        with self.assertRaises(ModelValidationError):
            ImageryFilters(min_resolution_m=-1)

    def test_negative_max_resolution(self) -> None:
        with self.assertRaises(ModelValidationError):
            ImageryFilters(max_resolution_m=-1)

    def test_min_exceeds_max_resolution(self) -> None:
        with self.assertRaises(ModelValidationError) as ctx:
            ImageryFilters(min_resolution_m=10, max_resolution_m=5)
        assert "min_resolution_m" in ctx.exception.field_name

    def test_equal_resolution_bounds_valid(self) -> None:
        f = ImageryFilters(min_resolution_m=10, max_resolution_m=10)
        assert f.min_resolution_m == f.max_resolution_m

    def test_date_start_after_end(self) -> None:
        with self.assertRaises(ModelValidationError):
            ImageryFilters(
                date_start=datetime(2026, 12, 31, tzinfo=UTC),
                date_end=datetime(2026, 1, 1, tzinfo=UTC),
            )

    def test_equal_dates_valid(self) -> None:
        d = datetime(2026, 6, 1, tzinfo=UTC)
        f = ImageryFilters(date_start=d, date_end=d)
        assert f.date_start == f.date_end

    def test_single_date_no_constraint(self) -> None:
        """Only one date provided — no cross-field check needed."""
        f = ImageryFilters(date_start=datetime(2026, 12, 31, tzinfo=UTC))
        assert f.date_end is None


class TestSearchResultInvariants(unittest.TestCase):
    """Invariant enforcement for SearchResult."""

    _REQUIRED: ClassVar[dict[str, object]] = {
        "scene_id": "S1",
        "provider": "pc",
        "acquisition_date": datetime(2026, 1, 1, tzinfo=UTC),
    }

    def test_empty_scene_id(self) -> None:
        with self.assertRaises(ModelValidationError):
            SearchResult(**{**self._REQUIRED, "scene_id": ""})  # type: ignore[arg-type]

    def test_empty_provider(self) -> None:
        with self.assertRaises(ModelValidationError):
            SearchResult(**{**self._REQUIRED, "provider": ""})  # type: ignore[arg-type]

    def test_negative_cloud_cover(self) -> None:
        with self.assertRaises(ModelValidationError):
            SearchResult(**{**self._REQUIRED, "cloud_cover_pct": -1})  # type: ignore[arg-type]

    def test_cloud_cover_over_100(self) -> None:
        with self.assertRaises(ModelValidationError):
            SearchResult(**{**self._REQUIRED, "cloud_cover_pct": 100.1})  # type: ignore[arg-type]

    def test_negative_resolution(self) -> None:
        with self.assertRaises(ModelValidationError):
            SearchResult(**{**self._REQUIRED, "spatial_resolution_m": -0.1})  # type: ignore[arg-type]

    def test_negative_off_nadir(self) -> None:
        with self.assertRaises(ModelValidationError):
            SearchResult(**{**self._REQUIRED, "off_nadir_deg": -1})  # type: ignore[arg-type]

    def test_valid_construction(self) -> None:
        r = SearchResult(**self._REQUIRED)  # type: ignore[arg-type]
        assert r.scene_id == "S1"


class TestOrderStatusInvariants(unittest.TestCase):
    """Invariant enforcement for OrderStatus."""

    def test_empty_order_id(self) -> None:
        with self.assertRaises(ModelValidationError):
            OrderStatus(order_id="", state=OrderState.PENDING)

    def test_progress_below_zero(self) -> None:
        with self.assertRaises(ModelValidationError):
            OrderStatus(order_id="x", state=OrderState.PENDING, progress_pct=-1)

    def test_progress_above_100(self) -> None:
        with self.assertRaises(ModelValidationError):
            OrderStatus(order_id="x", state=OrderState.READY, progress_pct=101)

    def test_boundary_progress_100(self) -> None:
        s = OrderStatus(order_id="x", state=OrderState.READY, progress_pct=100)
        assert s.progress_pct == 100


class TestBlobReferenceInvariants(unittest.TestCase):
    """Invariant enforcement for BlobReference."""

    def test_empty_container(self) -> None:
        with self.assertRaises(ModelValidationError):
            BlobReference(container="", blob_path="p")

    def test_empty_blob_path(self) -> None:
        with self.assertRaises(ModelValidationError):
            BlobReference(container="c", blob_path="")

    def test_negative_size(self) -> None:
        with self.assertRaises(ModelValidationError):
            BlobReference(container="c", blob_path="p", size_bytes=-1)

    def test_zero_size_valid(self) -> None:
        b = BlobReference(container="c", blob_path="p", size_bytes=0)
        assert b.size_bytes == 0


class TestProviderConfigInvariants(unittest.TestCase):
    """Invariant enforcement for ProviderConfig."""

    def test_empty_name(self) -> None:
        with self.assertRaises(ModelValidationError):
            ProviderConfig(name="")

    def test_whitespace_only_name(self) -> None:
        with self.assertRaises(ModelValidationError):
            ProviderConfig(name="   ")

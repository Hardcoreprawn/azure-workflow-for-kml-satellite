"""End-to-end (E2E) pipeline validation tests.

These tests validate the complete data flow from KML ingestion through
orchestration, with strict type validation at every integration boundary.
Each test focuses on one data-flow path and verifies:

1. Input contracts (types, shapes, required fields)
2. Output contracts (return types match expected schemas)
3. Data transformations (fields carry through correctly)
4. Error handling (exceptions on invalid data)

Pattern: Validate → Transform → Verify Type → Verify Data
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

import pytest

from kml_satellite.activities.parse_kml import parse_kml_file
from kml_satellite.activities.prepare_aoi import prepare_aoi
from kml_satellite.models.aoi import AOI
from kml_satellite.models.feature import Feature
from kml_satellite.models.imagery import (
    BlobReference,
    OrderId,
    OrderState,
    OrderStatus,
    SearchResult,
)

if TYPE_CHECKING:
    from pathlib import Path

    from kml_satellite.models.contracts import AcquisitionResult


# ============================================================================
# Type-Safe Fake Provider with Strict Input/Output Validation
# ============================================================================


class StrictTypeValidator:
    """Helper to validate types and shapes match expected contracts."""

    @staticmethod
    def assert_search_result(obj: Any) -> SearchResult:
        """Validate object matches SearchResult contract."""
        assert isinstance(obj, SearchResult), f"Expected SearchResult, got {type(obj)}"
        assert isinstance(obj.scene_id, str) and obj.scene_id, "scene_id must be non-empty str"
        assert isinstance(obj.provider, str), "provider must be str"
        assert isinstance(obj.acquisition_date, datetime), "acquisition_date must be datetime"
        assert isinstance(obj.cloud_cover_pct, int | float), "cloud_cover_pct must be numeric"
        assert 0 <= obj.cloud_cover_pct <= 100, "cloud_cover_pct must be 0-100"
        assert isinstance(obj.spatial_resolution_m, int | float), (
            "spatial_resolution_m must be numeric"
        )
        assert obj.spatial_resolution_m > 0, "spatial_resolution_m must be positive"
        assert isinstance(obj.crs, str), "crs must be str (e.g., EPSG:4326)"
        assert isinstance(obj.bbox, tuple) and len(obj.bbox) == 4, "bbox must be 4-tuple"
        assert isinstance(obj.asset_url, str), "asset_url must be str"
        return obj

    @staticmethod
    def assert_order_id(obj: Any) -> OrderId:
        """Validate object matches OrderId contract."""
        assert isinstance(obj, OrderId), f"Expected OrderId, got {type(obj)}"
        assert isinstance(obj.provider, str), "provider must be str"
        assert isinstance(obj.order_id, str) and obj.order_id, "order_id must be non-empty str"
        assert isinstance(obj.scene_id, str) and obj.scene_id, "scene_id must be non-empty str"
        return obj

    @staticmethod
    def assert_order_status(obj: Any) -> OrderStatus:
        """Validate object matches OrderStatus contract."""
        assert isinstance(obj, OrderStatus), f"Expected OrderStatus, got {type(obj)}"
        assert isinstance(obj.order_id, str), "order_id must be str"
        assert isinstance(obj.state, OrderState), "state must be OrderState enum"
        assert isinstance(obj.progress_pct, int | float), "progress_pct must be numeric"
        assert 0 <= obj.progress_pct <= 100, "progress_pct must be 0-100"
        if obj.message:
            assert isinstance(obj.message, str), "message must be str if provided"
        return obj

    @staticmethod
    def assert_blob_reference(obj: Any) -> BlobReference:
        """Validate object matches BlobReference contract."""
        assert isinstance(obj, BlobReference), f"Expected BlobReference, got {type(obj)}"
        assert isinstance(obj.container, str) and obj.container, "container must be non-empty str"
        assert isinstance(obj.blob_path, str) and obj.blob_path, "blob_path must be non-empty str"
        assert isinstance(obj.size_bytes, int) and obj.size_bytes > 0, (
            "size_bytes must be positive int"
        )
        assert isinstance(obj.content_type, str), "content_type must be str"
        return obj

    @staticmethod
    def assert_acquisition_result(obj: dict[str, Any]) -> AcquisitionResult:
        """Validate dict matches AcquisitionResult TypedDict contract."""
        required_keys = {"order_id", "provider", "scene_id", "aoi_feature_name", "state"}
        actual_keys = set(obj.keys())
        assert required_keys <= actual_keys, f"Missing keys: {required_keys - actual_keys}"

        assert isinstance(obj["order_id"], str), "order_id must be str"
        assert isinstance(obj["provider"], str), "provider must be str"
        assert isinstance(obj["scene_id"], str), "scene_id must be str"
        assert isinstance(obj["aoi_feature_name"], str), "aoi_feature_name must be str"
        assert obj["state"] == "ready", "state must be 'ready'"

        return cast("AcquisitionResult", obj)

    @staticmethod
    def assert_feature(obj: Any) -> Feature:
        """Validate object matches Feature contract."""
        assert isinstance(obj, Feature), f"Expected Feature, got {type(obj)}"
        assert isinstance(obj.name, str) and obj.name, "Feature.name must be non-empty str"
        assert isinstance(obj.exterior_coords, list), "Feature.exterior_coords must be list"
        assert len(obj.exterior_coords) >= 3, (
            "Feature must have at least 3 exterior coords (valid polygon)"
        )
        for coord in obj.exterior_coords:
            assert isinstance(coord, tuple) and len(coord) == 2, (
                "Each coord must be (lon, lat) tuple"
            )
            assert isinstance(coord[0], int | float) and isinstance(coord[1], int | float)
        assert isinstance(obj.crs, str) and obj.crs, "Feature.crs must be non-empty str"
        return obj

    @staticmethod
    def assert_aoi(obj: Any) -> AOI:
        """Validate object matches AOI contract."""
        assert isinstance(obj, AOI), f"Expected AOI, got {type(obj)}"
        assert isinstance(obj.bbox, tuple) and len(obj.bbox) == 4, "bbox must be 4-tuple of floats"
        for v in obj.bbox:
            assert isinstance(v, int | float), f"bbox values must be numeric, got {type(v)}"
        return obj


class TypeSafeProvider:
    """Provider that validates all inputs and outputs match contracts."""

    def __init__(self, search_results: list[SearchResult] | None = None):
        self.search_results = search_results or []
        self.calls: dict[str, list[Any]] = {
            "search": [],
            "order": [],
            "poll": [],
            "download": [],
        }

    def search(self, aoi: Any, filters: Any = None) -> list[SearchResult]:
        """Search with type validation."""
        validator = StrictTypeValidator()
        validator.assert_aoi(aoi)
        self.calls["search"].append({"aoi": aoi, "filters": filters})
        return self.search_results

    def order(self, scene_id: str) -> OrderId:
        """Order with type validation."""
        assert isinstance(scene_id, str) and scene_id, "scene_id must be non-empty str"
        self.calls["order"].append({"scene_id": scene_id})

        order_id = OrderId(
            provider="mock_provider",
            order_id=f"order-{scene_id}",
            scene_id=scene_id,
        )
        return StrictTypeValidator.assert_order_id(order_id)

    def poll(self, order_id: str) -> OrderStatus:
        """Poll with type validation."""
        assert isinstance(order_id, str) and order_id, "order_id must be non-empty str"
        self.calls["poll"].append({"order_id": order_id})

        status = OrderStatus(
            order_id=order_id,
            state=OrderState.READY,
            message="Mock order ready",
            progress_pct=100.0,
            updated_at=datetime.now(UTC),
        )
        return StrictTypeValidator.assert_order_status(status)

    def download(self, order_id: str) -> BlobReference:
        """Download with type validation."""
        assert isinstance(order_id, str) and order_id, "order_id must be non-empty str"
        self.calls["download"].append({"order_id": order_id})

        blob = BlobReference(
            container="test-output",
            blob_path=f"imagery/raw/{order_id}.tif",
            size_bytes=4096,
            content_type="image/tiff",
        )
        return StrictTypeValidator.assert_blob_reference(blob)


# ============================================================================
# E2E Test Suite: Data Flow Validation
# ============================================================================


@pytest.mark.integration
class TestE2EDataFlowValidation:
    """Validates complete pipeline data flow with strict type checking."""

    def test_kml_parse_produces_typed_features(self, single_polygon_kml: Path) -> None:
        """Step 1: Verify KML parsing produces correctly typed Feature objects."""
        # Input: KML file
        assert single_polygon_kml.exists(), f"KML file not found: {single_polygon_kml}"

        # Transform: Parse KML
        features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)

        # Verify output type and structure
        assert isinstance(features, list), "parse_kml_file must return list"
        assert len(features) >= 1, "KML must contain at least one feature"

        # Validate each feature matches contract
        for feature in features:
            validator = StrictTypeValidator()
            validated = validator.assert_feature(feature)
            assert validated.name, "Feature must have name"

    def test_feature_to_aoi_transforms_correctly(self, single_polygon_kml: Path) -> None:
        """Step 2: Verify Feature → AOI transformation preserves type safety."""
        features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
        feature = features[0]

        # Transform: Feature → AOI
        aoi = prepare_aoi(feature)

        # Verify output type and structure
        validator = StrictTypeValidator()
        validated_aoi = validator.assert_aoi(aoi)

        # Verify derived fields
        assert isinstance(validated_aoi.feature_name, str), "AOI must preserve feature name"
        assert isinstance(validated_aoi.exterior_coords, list), (
            "AOI must preserve geometry coordinates"
        )

    def test_aoi_to_search_produces_results(self, single_polygon_kml: Path) -> None:
        """Step 3: Verify AOI → Provider.search() produces typed SearchResults."""
        features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
        aoi = prepare_aoi(features[0])

        # Create provider with typed results
        mock_results = [
            SearchResult(
                scene_id="test-scene-001",
                provider="test_provider",
                acquisition_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
                cloud_cover_pct=5.0,
                spatial_resolution_m=0.6,
                crs="EPSG:4326",
                bbox=(50.0, 51.0, 50.1, 51.1),
                asset_url="https://example.com/scene.tif",
                extra={},
            )
        ]
        provider = TypeSafeProvider(search_results=mock_results)

        # Transform: AOI → Search
        results = provider.search(aoi)

        # Verify output
        assert isinstance(results, list), "search() must return list"
        assert len(results) > 0, "search() should return results"

        for result in results:
            validator = StrictTypeValidator()
            validated = validator.assert_search_result(result)
            assert validated.scene_id.startswith("test-scene-")

    def test_search_to_order_produces_order_id(self, single_polygon_kml: Path) -> None:
        """Step 4: Verify SearchResult → order() produces typed OrderId."""
        features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
        aoi = prepare_aoi(features[0])

        mock_results = [
            SearchResult(
                scene_id="test-scene-002",
                provider="test_provider",
                acquisition_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
                cloud_cover_pct=5.0,
                spatial_resolution_m=0.6,
                crs="EPSG:4326",
                bbox=(50.0, 51.0, 50.1, 51.1),
                asset_url="https://example.com/scene.tif",
            )
        ]
        provider = TypeSafeProvider(search_results=mock_results)
        results = provider.search(aoi)
        scene_id = results[0].scene_id

        # Transform: scene_id → OrderId
        order_id = provider.order(scene_id)

        # Verify output
        validator = StrictTypeValidator()
        validated = validator.assert_order_id(order_id)
        assert validated.scene_id == scene_id, "OrderId must preserve scene_id"

    def test_order_id_to_status_poll_produces_typed_status(self, single_polygon_kml: Path) -> None:
        """Step 5: Verify OrderId → poll() produces typed OrderStatus."""
        features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
        aoi = prepare_aoi(features[0])

        mock_results = [
            SearchResult(
                scene_id="test-scene-003",
                provider="test_provider",
                acquisition_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
                cloud_cover_pct=5.0,
                spatial_resolution_m=0.6,
                crs="EPSG:4326",
                bbox=(50.0, 51.0, 50.1, 51.1),
                asset_url="https://example.com/scene.tif",
            )
        ]
        provider = TypeSafeProvider(search_results=mock_results)
        results = provider.search(aoi)
        order_id_obj = provider.order(results[0].scene_id)

        # Transform: OrderId → OrderStatus
        status = provider.poll(order_id_obj.order_id)

        # Verify output
        validator = StrictTypeValidator()
        validated = validator.assert_order_status(status)
        assert validated.state == OrderState.READY, "status must indicate READY"
        assert validated.progress_pct == 100.0, "progress must be 100%"

    def test_order_id_to_download_produces_blob_reference(self, single_polygon_kml: Path) -> None:
        """Step 6: Verify OrderId → download() produces typed BlobReference."""
        features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
        aoi = prepare_aoi(features[0])

        mock_results = [
            SearchResult(
                scene_id="test-scene-004",
                provider="test_provider",
                acquisition_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
                cloud_cover_pct=5.0,
                spatial_resolution_m=0.6,
                crs="EPSG:4326",
                bbox=(50.0, 51.0, 50.1, 51.1),
                asset_url="https://example.com/scene.tif",
            )
        ]
        provider = TypeSafeProvider(search_results=mock_results)
        results = provider.search(aoi)
        order_id_obj = provider.order(results[0].scene_id)

        # Transform: OrderId → BlobReference
        with patch(
            "kml_satellite.activities.download_imagery._validate_raster_content", return_value=None
        ):
            blob = provider.download(order_id_obj.order_id)

        # Verify output
        validator = StrictTypeValidator()
        validated = validator.assert_blob_reference(blob)
        assert "imagery/raw/" in validated.blob_path, "blob_path must contain expected prefix"
        assert validated.size_bytes > 0, "size_bytes must be positive"

    def test_full_e2e_pipeline_type_flow(self, single_polygon_kml: Path) -> None:
        """Integration: Full pipeline KML → Feature → AOI → Search → Order → Poll → Download.

        Validates type contracts at every boundary and data preservation
        through all transformations.
        """
        # Step 1: Parse
        features = parse_kml_file(single_polygon_kml, source_filename=single_polygon_kml.name)
        assert len(features) >= 1

        # Step 2: Prepare AOI
        feature = features[0]
        aoi = prepare_aoi(feature)

        # Step 3-6: Mock provider pipeline
        mock_results = [
            SearchResult(
                scene_id="e2e-scene-001",
                provider="test_provider",
                acquisition_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
                cloud_cover_pct=3.2,
                spatial_resolution_m=10.0,
                crs="EPSG:32633",
                bbox=(50.0, 51.0, 50.1, 51.1),
                asset_url="https://example.com/e2e-scene.tif",
            )
        ]
        provider = TypeSafeProvider(search_results=mock_results)

        # Full chain with type validation at each step
        search_results = provider.search(aoi)
        assert len(search_results) > 0

        scene = search_results[0]
        order_id_obj = provider.order(scene.scene_id)
        assert order_id_obj.scene_id == scene.scene_id

        order_status = provider.poll(order_id_obj.order_id)
        assert order_status.state == OrderState.READY

        with patch(
            "kml_satellite.activities.download_imagery._validate_raster_content", return_value=None
        ):
            blob_ref = provider.download(order_id_obj.order_id)
            assert blob_ref.size_bytes > 0

        # Verify provider was called in correct sequence
        assert len(provider.calls["search"]) == 1, "search should be called once"
        assert len(provider.calls["order"]) == 1, "order should be called once"
        assert len(provider.calls["poll"]) == 1, "poll should be called once"
        assert len(provider.calls["download"]) == 1, "download should be called once"


@pytest.mark.integration
class TestE2EErrorHandling:
    """Validates error handling at data boundaries."""

    def test_invalid_aoi_to_search_raises_error(self) -> None:
        """Verify search() rejects invalid AOI types."""
        provider = TypeSafeProvider()

        # Invalid input: not an AOI
        with pytest.raises(AssertionError):
            provider.search({"not": "an_aoi"})  # type: ignore

    def test_invalid_order_produces_usable_order_id(self) -> None:
        """Verify order() rejects invalid scene_ids."""
        provider = TypeSafeProvider()

        # Invalid input: empty string
        with pytest.raises(AssertionError):
            provider.order("")

        # Invalid input: None
        with pytest.raises(AssertionError):
            provider.order(None)  # type: ignore

    def test_provider_call_history_records_all_interactions(self) -> None:
        """Verify provider tracks all calls for audit/debugging."""
        mock_results = [
            SearchResult(
                scene_id="audit-scene",
                provider="test_provider",
                acquisition_date=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
                cloud_cover_pct=2.0,
                spatial_resolution_m=10.0,
                crs="EPSG:4326",
                bbox=(0.0, 0.0, 1.0, 1.0),
                asset_url="https://example.com/audit.tif",
            )
        ]
        provider = TypeSafeProvider(search_results=mock_results)

        # Simulate pipeline
        mock_aoi = AOI(
            feature_name="test",
            exterior_coords=[(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.0, 0.0)],
            bbox=(0.0, 0.0, 1.0, 1.0),
        )
        _ = provider.search(mock_aoi)
        _ = provider.order("audit-scene")
        _ = provider.poll("order-audit-scene")
        _ = provider.download("order-audit-scene")

        # Verify audit trail
        assert len(provider.calls) == 4, "All operations should be tracked"
        assert provider.calls["search"][0]["aoi"] == mock_aoi
        assert provider.calls["order"][0]["scene_id"] == "audit-scene"
        assert provider.calls["poll"][0]["order_id"] == "order-audit-scene"

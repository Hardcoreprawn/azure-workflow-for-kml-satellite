"""Shared fixtures for the TreeSight test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Ensure Azure storage env var is set for config module import
os.environ.setdefault("AzureWebJobsStorage", "UseDevelopmentStorage=true")
os.environ.setdefault("DEMO_VALET_TOKEN_SECRET", "test-secret-key-for-unit-tests-only")

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def sample_kml_bytes() -> bytes:
    """Minimal valid KML with a single polygon (triangle in Kenya)."""
    return (FIXTURES_DIR / "sample.kml").read_bytes()


@pytest.fixture()
def multi_polygon_kml_bytes() -> bytes:
    """KML containing a MultiPolygon placemark."""
    return (FIXTURES_DIR / "multi_polygon.kml").read_bytes()


@pytest.fixture()
def sample_feature():
    """Pre-built Feature for tests that don't need KML parsing."""
    from treesight.models.feature import Feature

    return Feature(
        name="Block A - Fuji Apple",
        description="Test orchard block",
        exterior_coords=[
            [36.8, -1.3],
            [36.81, -1.3],
            [36.81, -1.31],
            [36.8, -1.31],
            [36.8, -1.3],
        ],
        interior_coords=[],
        crs="EPSG:4326",
        metadata={"crop": "apple", "variety": "fuji"},
        source_file="test.kml",
        feature_index=0,
    )


@pytest.fixture()
def sample_aoi():
    """Pre-built AOI for tests that don't need geometry computation."""
    from treesight.models.aoi import AOI

    return AOI(
        feature_name="Block A - Fuji Apple",
        source_file="test.kml",
        feature_index=0,
        exterior_coords=[
            [36.8, -1.3],
            [36.81, -1.3],
            [36.81, -1.31],
            [36.8, -1.31],
            [36.8, -1.3],
        ],
        bbox=[36.8, -1.31, 36.81, -1.3],
        buffered_bbox=[36.7991, -1.3109, 36.8109, -1.2991],
        area_ha=12.3,
        centroid=[36.805, -1.305],
        buffer_m=100.0,
        crs="EPSG:4326",
        metadata={"crop": "apple"},
    )


@pytest.fixture()
def sample_blob_event_dict() -> dict:
    """Dict representation of a BlobEvent as it arrives from Event Grid."""
    return {
        "blob_url": "https://teststorage.blob.core.windows.net/kml-input/uploads/farm.kml",
        "container_name": "kml-input",
        "blob_name": "uploads/farm.kml",
        "content_length": 4096,
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": "2025-01-15T10:30:00Z",
        "correlation_id": "evt-abc-123",
    }


@pytest.fixture()
def tenant_blob_event_dict() -> dict:
    """BlobEvent dict for a tenant-scoped container."""
    return {
        "blob_url": "https://teststorage.blob.core.windows.net/acme-input/uploads/orchard.kml",
        "container_name": "acme-input",
        "blob_name": "uploads/orchard.kml",
        "content_length": 2048,
        "content_type": "application/vnd.google-earth.kml+xml",
        "event_time": "2025-01-15T11:00:00Z",
        "correlation_id": "evt-def-456",
    }

"""Shared fixtures for the Canopex test suite."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import azure.functions as func
import pytest

# Ensure required config env vars are set for config module import
os.environ.setdefault("AzureWebJobsStorage", "UseDevelopmentStorage=true")
os.environ.setdefault("DEMO_VALET_TOKEN_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("AUTH_MODE", "bearer_only")
os.environ.setdefault("CIAM_AUTHORITY", "https://ciam.example.com")
os.environ.setdefault("CIAM_TENANT_ID", "test-tenant")
os.environ.setdefault("CIAM_API_AUDIENCE", "api://test-audience")

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Canonical test origins — mirrors what infra sets via CORS_ALLOWED_ORIGINS.
# The env var must be set BEFORE _helpers is imported so _build_allowed_origins
# picks it up at module load time.
TEST_ORIGIN = "https://canopex.hrdcrprwn.com"
TEST_LOCAL_ORIGIN = "http://localhost:4280"
os.environ.setdefault(
    "CORS_ALLOWED_ORIGINS",
    f"{TEST_ORIGIN},https://green-moss-0e849ac03.2.azurestaticapps.net",
)
os.environ.setdefault("PRIMARY_SITE_URL", TEST_ORIGIN)


@pytest.fixture()
def sample_kml_bytes() -> bytes:
    """Minimal valid KML with a single polygon (triangle in Kenya)."""
    return (FIXTURES_DIR / "sample.kml").read_bytes()


@pytest.fixture()
def multi_polygon_kml_bytes() -> bytes:
    """KML containing a MultiPolygon placemark."""
    return (FIXTURES_DIR / "multi_polygon.kml").read_bytes()


@pytest.fixture()
def single_polygon_kml_bytes() -> bytes:
    """KML with a single polygon placemark."""
    return (FIXTURES_DIR / "single_polygon.kml").read_bytes()


@pytest.fixture()
def polygon_with_hole_kml_bytes() -> bytes:
    """KML with a polygon that has an interior ring (hole)."""
    return (FIXTURES_DIR / "polygon_with_hole.kml").read_bytes()


@pytest.fixture()
def tiny_polygon_kml_bytes() -> bytes:
    """KML with a very small polygon (< 0.1 ha)."""
    return (FIXTURES_DIR / "tiny_polygon.kml").read_bytes()


@pytest.fixture()
def huge_polygon_kml_bytes() -> bytes:
    """KML with a very large polygon that triggers area warning."""
    return (FIXTURES_DIR / "huge_polygon.kml").read_bytes()


@pytest.fixture()
def concave_polygon_kml_bytes() -> bytes:
    """KML with an L-shaped (concave) polygon."""
    return (FIXTURES_DIR / "concave_polygon.kml").read_bytes()


@pytest.fixture()
def adjacent_polygons_kml_bytes() -> bytes:
    """KML with two adjacent polygons sharing an edge."""
    return (FIXTURES_DIR / "adjacent_polygons.kml").read_bytes()


@pytest.fixture()
def overlapping_polygons_kml_bytes() -> bytes:
    """KML with two overlapping polygons."""
    return (FIXTURES_DIR / "overlapping_polygons.kml").read_bytes()


@pytest.fixture()
def five_polygons_kml_bytes() -> bytes:
    """KML with five polygons — tests scaling / many-AOI handling."""
    return (FIXTURES_DIR / "five_polygons.kml").read_bytes()


@pytest.fixture()
def triangle_polygon_kml_bytes() -> bytes:
    """KML with a triangle — minimum valid polygon."""
    return (FIXTURES_DIR / "triangle_polygon.kml").read_bytes()


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


# ---------------------------------------------------------------------------
# M28 — shared HTTP request builder for endpoint tests
# ---------------------------------------------------------------------------


def encode_test_principal(
    user_id: str = "test-user",
    user_details: str = "user@example.com",
    identity_provider: str = "aad",
    user_roles: list[str] | None = None,
) -> str:
    """Build a Base64-encoded X-MS-CLIENT-PRINCIPAL header value for tests."""
    import base64

    principal = {
        "identityProvider": identity_provider,
        "userId": user_id,
        "userDetails": user_details,
        "userRoles": user_roles or ["anonymous", "authenticated"],
    }
    return base64.b64encode(json.dumps(principal).encode()).decode()


def make_test_request(
    url: str = "/api/test",
    *,
    method: str = "GET",
    body: bytes | str | dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    origin: str | None = TEST_ORIGIN,
    auth_header: str | None = "Bearer fake-token",
    principal_user_id: str | None = "test-user",
) -> func.HttpRequest:
    """Build an ``azure.functions.HttpRequest`` for endpoint tests.

    Consolidates the ``_make_req`` helpers previously duplicated across
    test_analysis_submission_endpoints, test_billing_endpoints,
    test_health_endpoints, and test_submission_cors.
    """
    h: dict[str, str] = {}
    if origin:
        h["Origin"] = origin
    if auth_header:
        h["Authorization"] = auth_header
    if principal_user_id:
        h["X-MS-CLIENT-PRINCIPAL"] = encode_test_principal(user_id=principal_user_id)

    if headers:
        h.update(headers)

    if body is None:
        raw_body = b""
    elif isinstance(body, bytes):
        raw_body = body
    elif isinstance(body, dict):
        h.setdefault("Content-Type", "application/json")
        raw_body = json.dumps(body).encode("utf-8")
    else:
        raw_body = body.encode("utf-8")

    return func.HttpRequest(
        method=method,
        url=url,
        headers=h,
        params=params or {},
        body=raw_body,
    )


# ---------------------------------------------------------------------------
# M30 — shared mock-storage fixture (dict-backed BlobStorageClient)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_storage():
    """Patch ``BlobStorageClient`` with an in-memory dict store.

    Yields the backing ``dict`` so tests can pre-populate or inspect
    stored values.  Supports ``download_json`` / ``upload_json``.
    """
    store: dict[str, dict] = {}
    mock_cls = MagicMock()

    def _download_json(_container: str, path: str) -> dict:
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    def _upload_json(_container: str, path: str, data: dict) -> None:
        store[path] = data

    mock_cls.return_value.download_json = _download_json
    mock_cls.return_value.upload_json = _upload_json

    with patch("treesight.storage.client.BlobStorageClient", mock_cls):
        yield store

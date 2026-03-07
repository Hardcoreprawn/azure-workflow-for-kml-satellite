"""Tests for Blob Storage tenant repository.

Phase 5 #71: Blob Storage JSON data layer (tenants + jobs).

Tests CRUD operations for Tenant documents with mocked Blob Storage client.

References:
    PID § 7.6 (Tenant State - architecture agnostic)
    ROADMAP Phase 5 #71 (Blob Storage MVP)
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from azure.core.exceptions import ResourceNotFoundError

from kml_satellite.data.tenant_repository import TenantRepository
from kml_satellite.models.tenants import Tenant, TenantTier


class TestTenantRepository(unittest.TestCase):
    """Repository for Tenant CRUD operations via Blob Storage JSON."""

    def test_create_tenant(self) -> None:
        """Create a new tenant document."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = TenantRepository(mock_container)
            tenant = Tenant(
                tenant_id="tenant-001",
                name="Test Tenant",
                email="test@example.com",
                tier=TenantTier.FREE,
                created_at=datetime(2026, 3, 1, tzinfo=UTC),
            )

            repo.create(tenant)

            # Verify blob upload was called
            mock_container.get_blob_client.assert_called_once_with("tenants/tenant-001.json")
            mock_blob_client.upload_blob.assert_called_once()

            # Verify payload is JSON
            call_args = mock_blob_client.upload_blob.call_args
            payload = call_args[0][0]
            doc = json.loads(payload)
            assert doc["tenant_id"] == "tenant-001"

    def test_get_tenant_found(self) -> None:
        """Get an existing tenant by ID."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_blob_download = MagicMock()
            mock_blob_client.download_blob.return_value = mock_blob_download
            mock_blob_download.readall.return_value = json.dumps(
                {
                    "tenant_id": "tenant-001",
                    "name": "Test Tenant",
                    "email": "test@example.com",
                    "tier": "free",
                    "created_at": "2026-03-01T00:00:00+00:00",
                    "enabled": True,
                }
            ).encode()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = TenantRepository(mock_container)
            tenant = repo.get("tenant-001")

            assert tenant is not None
            assert tenant.tenant_id == "tenant-001"
            assert tenant.name == "Test Tenant"
            assert tenant.tier == TenantTier.FREE

            # Verify correct blob path
            mock_container.get_blob_client.assert_called_once_with("tenants/tenant-001.json")

    def test_get_tenant_not_found(self) -> None:
        """Get returns None when tenant doesn't exist."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_blob_client.download_blob.side_effect = ResourceNotFoundError(message="Not found")
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = TenantRepository(mock_container)
            tenant = repo.get("nonexistent")

            assert tenant is None

    def test_get_tenant_corrupt_json(self) -> None:
        """Get returns None for corrupt JSON blob."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_blob_download = MagicMock()
            mock_blob_client.download_blob.return_value = mock_blob_download
            mock_blob_download.readall.return_value = b"{ invalid json"
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = TenantRepository(mock_container)
            tenant = repo.get("bad-json")

            assert tenant is None

    def test_update_tenant(self) -> None:
        """Update an existing tenant."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = TenantRepository(mock_container)
            tenant = Tenant(
                tenant_id="tenant-001",
                name="Updated Name",
                email="updated@example.com",
                tier=TenantTier.PRO,
                created_at=datetime(2026, 3, 1, tzinfo=UTC),
            )

            repo.update(tenant)

            # Verify upload with overwrite=True
            call_args = mock_blob_client.upload_blob.call_args
            assert call_args[1].get("overwrite") is True

    def test_delete_tenant(self) -> None:
        """Delete a tenant by ID."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = TenantRepository(mock_container)
            repo.delete("tenant-001")

            mock_container.get_blob_client.assert_called_once_with("tenants/tenant-001.json")
            mock_blob_client.delete_blob.assert_called_once()

    def test_delete_tenant_not_found(self) -> None:
        """Delete silently ignores nonexistent tenant."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            mock_blob_client = MagicMock()
            mock_blob_client.delete_blob.side_effect = ResourceNotFoundError(message="Not found")
            mock_container.get_blob_client.return_value = mock_blob_client

            repo = TenantRepository(mock_container)
            # Should not raise
            repo.delete("nonexistent")

    def test_list_all_tenants(self) -> None:
        """List all tenants by scanning prefix."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            # Mock list_blobs to return two tenant blobs
            mock_blob1 = MagicMock()
            mock_blob1.name = "tenants/tenant-001.json"
            mock_blob2 = MagicMock()
            mock_blob2.name = "tenants/tenant-002.json"
            mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]

            # Mock get_blob_client for each blob
            mock_blob_client1 = MagicMock()
            mock_blob_download1 = MagicMock()
            mock_blob_client1.download_blob.return_value = mock_blob_download1
            mock_blob_download1.readall.return_value = json.dumps(
                {
                    "tenant_id": "tenant-001",
                    "name": "Tenant 1",
                    "email": "t1@example.com",
                    "tier": "free",
                    "created_at": "2026-03-01T00:00:00+00:00",
                    "enabled": True,
                }
            ).encode()

            mock_blob_client2 = MagicMock()
            mock_blob_download2 = MagicMock()
            mock_blob_client2.download_blob.return_value = mock_blob_download2
            mock_blob_download2.readall.return_value = json.dumps(
                {
                    "tenant_id": "tenant-002",
                    "name": "Tenant 2",
                    "email": "t2@example.com",
                    "tier": "pro",
                    "created_at": "2026-03-02T00:00:00+00:00",
                    "enabled": True,
                }
            ).encode()

            def get_blob_side_effect(path: str) -> MagicMock:
                if path == "tenants/tenant-001.json":
                    return mock_blob_client1
                return mock_blob_client2

            mock_container.get_blob_client.side_effect = get_blob_side_effect

            repo = TenantRepository(mock_container)
            tenants = repo.list_all()

            assert len(tenants) == 2
            assert tenants[0].tenant_id == "tenant-001"
            assert tenants[1].tenant_id == "tenant-002"

    def test_list_by_tier(self) -> None:
        """List tenants filtered by tier."""
        with patch("azure.storage.blob.ContainerClient") as mock_container:
            # Mock list_blobs
            mock_blob1 = MagicMock()
            mock_blob1.name = "tenants/tenant-pro-1.json"
            mock_blob2 = MagicMock()
            mock_blob2.name = "tenants/tenant-free-1.json"
            mock_container.list_blobs.return_value = [mock_blob1, mock_blob2]

            # Mock get_blob_client
            mock_blob_client1 = MagicMock()
            mock_blob_download1 = MagicMock()
            mock_blob_client1.download_blob.return_value = mock_blob_download1
            mock_blob_download1.readall.return_value = json.dumps(
                {
                    "tenant_id": "tenant-pro-1",
                    "name": "Pro Tenant",
                    "email": "pro@example.com",
                    "tier": "pro",
                    "created_at": "2026-03-01T00:00:00+00:00",
                    "enabled": True,
                }
            ).encode()

            mock_blob_client2 = MagicMock()
            mock_blob_download2 = MagicMock()
            mock_blob_client2.download_blob.return_value = mock_blob_download2
            mock_blob_download2.readall.return_value = json.dumps(
                {
                    "tenant_id": "tenant-free-1",
                    "name": "Free Tenant",
                    "email": "free@example.com",
                    "tier": "free",
                    "created_at": "2026-03-02T00:00:00+00:00",
                    "enabled": True,
                }
            ).encode()

            def get_blob_side_effect(path: str) -> MagicMock:
                if "pro" in path:
                    return mock_blob_client1
                return mock_blob_client2

            mock_container.get_blob_client.side_effect = get_blob_side_effect

            repo = TenantRepository(mock_container)
            tenants = repo.list_by_tier(TenantTier.PRO)

            assert len(tenants) == 1
            assert tenants[0].tier == TenantTier.PRO

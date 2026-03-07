"""Tenant repository for Blob Storage JSON operations.

Phase 5 #71: Blob Storage JSON data layer (tenants + jobs).

Stores tenant and job documents as JSON blobs in Azure Blob Storage.
Kept lean and "ghetto" for MVP - no Cosmos DB overhead, minimal cost.

Blob organization:
    {container}/tenants/{tenant_id}.json
    {container}/jobs/{tenant_id}/{job_id}.json

Margaret Hamilton principles:
- Explicit error handling for Blob Storage exceptions
- Defensive JSON parsing with fallback defaults
- Minimal dependencies (no extra Azure services)
- Readable blob paths for debugging

References:
    PID § 7.6 (Tenant State - architecture agnostic)
    ROADMAP Phase 5 #71 (Blob Storage MVP)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from azure.core.exceptions import ResourceNotFoundError

from kml_satellite.models.tenants import Tenant, TenantTier

if TYPE_CHECKING:
    from azure.storage.blob import ContainerClient

logger = logging.getLogger(__name__)


class TenantRepository:
    """Repository for Tenant CRUD operations in Blob Storage JSON.

    Encapsulates blob storage operations with type-safe Pydantic model conversion.
    Tenant documents stored at: {container}/tenants/{tenant_id}.json

    Args:
        container: Blob ContainerClient for the data container.
    """

    _TENANTS_PREFIX = "tenants"

    def __init__(self, container: ContainerClient) -> None:
        self._container = container

    def _tenant_blob_path(self, tenant_id: str) -> str:
        """Generate blob path for a tenant document.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Blob path (e.g., "tenants/tenant-001.json").
        """
        return f"{self._TENANTS_PREFIX}/{tenant_id}.json"

    def create(self, tenant: Tenant) -> None:
        """Create a new tenant document.

        Args:
            tenant: Tenant model to persist.

        Raises:
            Exception: On blob upload failure (retryable).
        """
        blob_path = self._tenant_blob_path(tenant.tenant_id)
        payload = tenant.model_dump_json()
        try:
            blob_client = self._container.get_blob_client(blob_path)
            blob_client.upload_blob(payload, overwrite=False)
            logger.info(
                "Tenant created: %s (tier=%s) → %s",
                tenant.tenant_id,
                tenant.tier.value,
                blob_path,
            )
        except Exception as exc:
            logger.error("Failed to create tenant %s: %s", tenant.tenant_id, exc)
            raise

    def get(self, tenant_id: str) -> Tenant | None:
        """Retrieve a tenant by ID.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Tenant model if found, None otherwise.

        Raises:
            Exception: On blob download failure (retryable, except 404).
        """
        blob_path = self._tenant_blob_path(tenant_id)
        try:
            blob_client = self._container.get_blob_client(blob_path)
            payload = blob_client.download_blob().readall()
            doc = json.loads(payload)
            return Tenant.model_validate(doc)
        except ResourceNotFoundError:
            logger.debug("Tenant not found: %s (blob: %s)", tenant_id, blob_path)
            return None
        except json.JSONDecodeError as exc:
            logger.error("Corrupt tenant blob %s: %s", blob_path, exc)
            return None
        except Exception as exc:
            logger.error("Failed to get tenant %s: %s", tenant_id, exc)
            raise

    def update(self, tenant: Tenant) -> None:
        """Update an existing tenant document.

        Uses overwrite=True, so creates if missing.

        Args:
            tenant: Tenant model with updated fields.

        Raises:
            Exception: On blob upload failure (retryable).
        """
        blob_path = self._tenant_blob_path(tenant.tenant_id)
        payload = tenant.model_dump_json()
        try:
            blob_client = self._container.get_blob_client(blob_path)
            blob_client.upload_blob(payload, overwrite=True)
            logger.info("Tenant updated: %s → %s", tenant.tenant_id, blob_path)
        except Exception as exc:
            logger.error("Failed to update tenant %s: %s", tenant.tenant_id, exc)
            raise

    def delete(self, tenant_id: str) -> None:
        """Delete a tenant by ID.

        Margaret Hamilton: This is a destructive operation. Caller must ensure
        tenant has no active jobs/acquisitions before deletion.

        Args:
            tenant_id: Tenant identifier.

        Raises:
            Exception: On blob delete failure (retryable, except 404).
        """
        blob_path = self._tenant_blob_path(tenant_id)
        try:
            blob_client = self._container.get_blob_client(blob_path)
            blob_client.delete_blob()
            logger.info("Tenant deleted: %s (blob: %s)", tenant_id, blob_path)
        except ResourceNotFoundError:
            logger.warning("Attempted to delete nonexistent tenant: %s", tenant_id)
        except Exception as exc:
            logger.error("Failed to delete tenant %s: %s", tenant_id, exc)
            raise

    def list_all(self) -> list[Tenant]:
        """List all tenants by scanning tenants/ prefix.

        Warning: Expensive for large tenant counts. Use for admin dashboards only.

        Returns:
            List of all Tenant models found.

        Raises:
            Exception: On blob listing failure (retryable).
        """
        try:
            tenants: list[Tenant] = []
            blobs = self._container.list_blobs(name_starts_with=self._TENANTS_PREFIX)
            for blob in blobs:
                try:
                    blob_client = self._container.get_blob_client(blob.name)
                    payload = blob_client.download_blob().readall()
                    doc = json.loads(payload)
                    tenant = Tenant.model_validate(doc)
                    tenants.append(tenant)
                except (json.JSONDecodeError, ValueError):
                    logger.warning("Skipping corrupt tenant blob: %s", blob.name)
                    continue
            logger.debug("Listed %d tenants from blob storage", len(tenants))
            return tenants
        except Exception as exc:
            logger.error("Failed to list tenants: %s", exc)
            raise

    def list_by_tier(self, tier: TenantTier) -> list[Tenant]:
        """List tenants filtered by subscription tier.

        Scans all tenants and filters in-memory (no server-side query).

        Args:
            tier: Subscription tier to filter by.

        Returns:
            List of Tenant models matching the tier.

        Raises:
            Exception: On blob listing failure (retryable).
        """
        all_tenants = self.list_all()
        filtered = [t for t in all_tenants if t.tier == tier]
        logger.debug("Listed %d tenants for tier=%s", len(filtered), tier.value)
        return filtered

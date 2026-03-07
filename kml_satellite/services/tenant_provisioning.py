"""Tenant provisioning service for Azure KML Satellite workflow.

Phase 5 #72: Operator-triggered tenant provisioning.

This service handles provisioning of new tenants by:
1. Creating a tenant record in the data layer
2. Creating blob containers for tenant-isolated storage
3. Setting tier-appropriate quota limits

Margaret Hamilton principles:
- Idempotency not guaranteed: duplicate provision raises TenantAlreadyExistsError
- Fail-fast on validation errors
- Log all provisioning operations for audit trail
"""

import logging
from datetime import UTC, datetime

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient
from pydantic import BaseModel, Field

from kml_satellite.data.tenant_repository import TenantRepository
from kml_satellite.models.tenants import Tenant, TenantTier

logger = logging.getLogger(__name__)


class TenantAlreadyExistsError(Exception):
    """Raised when attempting to provision a tenant that already exists."""

    pass


class ProvisioningRequest(BaseModel):
    """Request model for tenant provisioning.

    Attributes:
        tenant_id: Unique identifier for tenant (immutable, used in blob paths).
        name: Display name for tenant organization.
        email: Primary contact email for tenant.
        tier: Subscription tier determining quota limits.
    """

    tenant_id: str = Field(..., description="Unique tenant identifier")
    name: str = Field(..., description="Tenant organization name")
    email: str = Field(..., description="Primary contact email")
    tier: TenantTier = Field(..., description="Subscription tier")


# Tier-specific quota mappings
TIER_QUOTAS = {
    TenantTier.FREE: {
        "max_aoi_count": 10,
        "max_imagery_gb_per_month": 5,
    },
    TenantTier.PRO: {
        "max_aoi_count": 100,
        "max_imagery_gb_per_month": 50,
    },
    TenantTier.ENTERPRISE: {
        "max_aoi_count": None,  # Unlimited
        "max_imagery_gb_per_month": None,  # Unlimited
    },
}


class TenantProvisioningService:
    """Service for provisioning new tenants.

    Handles tenant creation, blob container setup, and quota assignment.

    Args:
        tenant_repo: Repository for tenant data persistence.
        blob_service_client: Azure Blob Storage service client for creating containers.
    """

    def __init__(
        self,
        tenant_repo: TenantRepository,
        blob_service_client: BlobServiceClient,
    ):
        """Initialize provisioning service with dependencies."""
        self.tenant_repo = tenant_repo
        self.blob_service_client = blob_service_client

    def provision_tenant(self, request: ProvisioningRequest) -> Tenant:
        """Provision a new tenant with isolated blob containers.

        Steps:
        1. Check if tenant already exists (raise error if duplicate)
        2. Create tenant record with tier-specific quotas
        3. Create blob containers: {tenant_id}-input, {tenant_id}-output

        Args:
            request: Provisioning request containing tenant details.

        Returns:
            Created Tenant instance.

        Raises:
            TenantAlreadyExistsError: If tenant_id already exists.

        Margaret Hamilton: Fail-fast on duplicate tenant to prevent
        state corruption. Operator must explicitly delete old tenant first.
        """
        tenant_id = request.tenant_id
        logger.info(f"Provisioning tenant: {tenant_id}")

        # Step 1: Check for existing tenant
        existing = self.tenant_repo.get(tenant_id)
        if existing:
            logger.warning(f"Provisioning failed: tenant '{tenant_id}' already exists")
            raise TenantAlreadyExistsError(f"Tenant '{tenant_id}' already exists")

        # Step 2: Create tenant record with tier quotas
        quotas = TIER_QUOTAS[request.tier]
        tenant = Tenant(
            tenant_id=tenant_id,
            name=request.name,
            email=request.email,
            tier=request.tier,
            created_at=datetime.now(UTC),
            enabled=True,
            max_aoi_count=quotas["max_aoi_count"],
            max_imagery_gb_per_month=quotas["max_imagery_gb_per_month"],
        )
        self.tenant_repo.create(tenant)
        logger.info(f"Created tenant record: {tenant_id} (tier={request.tier})")

        # Step 3: Create blob containers
        self._create_tenant_containers(tenant_id)

        logger.info(f"Successfully provisioned tenant: {tenant_id}")
        return tenant

    def _create_tenant_containers(self, tenant_id: str) -> None:
        """Create blob containers for tenant-isolated storage.

        Creates:
        - {tenant_id}-input: For KML uploads
        - {tenant_id}-output: For processed images and metadata

        Args:
            tenant_id: Tenant identifier for container naming.

        Margaret Hamilton: Container creation is not transactional with tenant
        record creation. If this fails, operator must manually provision containers
        or re-run provisioning (but will hit TenantAlreadyExistsError).
        Future: Add rollback or idempotent container creation.
        """
        input_container = f"{tenant_id}-input"
        output_container = f"{tenant_id}-output"

        for container_name in [input_container, output_container]:
            try:
                self.blob_service_client.create_container(container_name)
                logger.info(f"Created blob container: {container_name}")
            except ResourceExistsError:
                logger.warning(f"Container already exists: {container_name}")
                # Not an error - may have been created manually or by previous partial run

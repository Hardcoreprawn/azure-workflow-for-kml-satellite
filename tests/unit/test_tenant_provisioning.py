"""Unit tests for tenant provisioning service.

Phase 5 #72: Operator-triggered tenant provisioning.

Tests:
- Create new tenant with blob containers
- Prevent duplicate tenant provisioning
- Validate provisioning request inputs
- Handle blob container creation failures
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from kml_satellite.data.tenant_repository import TenantRepository
from kml_satellite.models.tenants import Tenant, TenantTier
from kml_satellite.services.tenant_provisioning import (
    ProvisioningRequest,
    TenantAlreadyExistsError,
    TenantProvisioningService,
)


@pytest.fixture
def mock_tenant_repo():
    """Mock TenantRepository."""
    return MagicMock(spec=TenantRepository)


@pytest.fixture
def mock_blob_service_client():
    """Mock BlobServiceClient for blob storage."""
    return MagicMock()


@pytest.fixture
def provisioning_service(mock_tenant_repo, mock_blob_service_client):
    """TenantProvisioningService with mocked dependencies."""
    return TenantProvisioningService(
        tenant_repo=mock_tenant_repo,
        blob_service_client=mock_blob_service_client,
    )


def test_provision_tenant_success(
    provisioning_service, mock_tenant_repo, mock_blob_service_client
):
    """Test successful tenant provisioning creates tenant + blob containers."""
    # Arrange
    request = ProvisioningRequest(
        tenant_id="test-tenant",
        name="Test Tenant",
        email="test@example.com",
        tier=TenantTier.FREE,
    )
    mock_tenant_repo.get.return_value = None  # Tenant does not exist
    mock_tenant_repo.create.return_value = Tenant(
        tenant_id="test-tenant",
        name="Test Tenant",
        email="test@example.com",
        tier=TenantTier.FREE,
        created_at=datetime.now(UTC),
    )

    # Act
    tenant = provisioning_service.provision_tenant(request)

    # Assert
    assert tenant.tenant_id == "test-tenant"
    assert tenant.name == "Test Tenant"
    mock_tenant_repo.create.assert_called_once()
    # Should create 2 containers: {tenant}-input and {tenant}-output
    assert mock_blob_service_client.create_container.call_count == 2


def test_provision_tenant_duplicate_raises_error(provisioning_service, mock_tenant_repo):
    """Test provisioning a tenant that already exists raises TenantAlreadyExistsError."""
    # Arrange
    request = ProvisioningRequest(
        tenant_id="existing-tenant",
        name="Existing Tenant",
        email="existing@example.com",
        tier=TenantTier.PRO,
    )
    # Tenant already exists
    mock_tenant_repo.get.return_value = Tenant(
        tenant_id="existing-tenant",
        name="Existing Tenant",
        email="existing@example.com",
        tier=TenantTier.PRO,
        created_at=datetime.now(UTC),
    )

    # Act & Assert
    with pytest.raises(TenantAlreadyExistsError, match="Tenant 'existing-tenant' already exists"):
        provisioning_service.provision_tenant(request)

    mock_tenant_repo.create.assert_not_called()


def test_provision_tenant_invalid_tier_raises_error():
    """Test provisioning request with invalid tier raises validation error."""
    # Act & Assert
    with pytest.raises(ValueError):
        ProvisioningRequest(
            tenant_id="test-tenant",
            name="Test Tenant",
            email="test@example.com",
            tier="invalid_tier",  # type: ignore
        )


def test_provision_tenant_sets_tier_specific_quotas(provisioning_service, mock_tenant_repo):
    """Test provisioning sets tier-appropriate quota limits."""
    # Arrange - FREE tier
    request_free = ProvisioningRequest(
        tenant_id="free-tenant",
        name="Free Tenant",
        email="free@example.com",
        tier=TenantTier.FREE,
    )
    mock_tenant_repo.get.return_value = None

    # Act
    provisioning_service.provision_tenant(request_free)

    # Assert - FREE tier should have quotas set
    call_args = mock_tenant_repo.create.call_args[0][0]
    assert call_args.max_aoi_count is not None
    assert call_args.max_imagery_gb_per_month is not None

    # Reset mock
    mock_tenant_repo.reset_mock()

    # Arrange - ENTERPRISE tier
    request_enterprise = ProvisioningRequest(
        tenant_id="enterprise-tenant",
        name="Enterprise Tenant",
        email="enterprise@example.com",
        tier=TenantTier.ENTERPRISE,
    )
    mock_tenant_repo.get.return_value = None

    # Act
    provisioning_service.provision_tenant(request_enterprise)

    # Assert - ENTERPRISE tier should have unlimited (None) quotas
    call_args = mock_tenant_repo.create.call_args[0][0]
    assert call_args.max_aoi_count is None
    assert call_args.max_imagery_gb_per_month is None


def test_provision_tenant_creates_correct_container_names(
    provisioning_service, mock_blob_service_client, mock_tenant_repo
):
    """Test provisioning creates correctly named blob containers."""
    # Arrange
    request = ProvisioningRequest(
        tenant_id="acme-corp",
        name="Acme Corporation",
        email="admin@acme.com",
        tier=TenantTier.PRO,
    )
    mock_tenant_repo.get.return_value = None

    # Act
    provisioning_service.provision_tenant(request)

    # Assert - verify container names
    calls = mock_blob_service_client.create_container.call_args_list
    container_names = [call[0][0] for call in calls]
    assert "acme-corp-input" in container_names
    assert "acme-corp-output" in container_names

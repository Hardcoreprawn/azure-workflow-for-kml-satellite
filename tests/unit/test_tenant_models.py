"""Tests for tenant and job Cosmos DB models.

Phase 5 #71: Cosmos DB data layer (tenants + jobs containers).

References:
    PID § 7.6 (Tenant State - Cosmos DB schema)
    ARCHITECTURE_REVIEW § 4.2 (Cosmos DB Data Layer)
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from kml_satellite.models.tenants import Job, JobStatus, Tenant, TenantTier


class TestTenant(unittest.TestCase):
    """Tenant model (Cosmos DB tenants container)."""

    def test_minimal_tenant_creation(self) -> None:
        """Tenant can be created with minimal required fields."""
        tenant = Tenant(
            tenant_id="tenant-001",
            name="Test Tenant",
            email="test@example.com",
            tier=TenantTier.FREE,
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        assert tenant.tenant_id == "tenant-001"
        assert tenant.name == "Test Tenant"
        assert tenant.email == "test@example.com"
        assert tenant.tier == TenantTier.FREE
        assert tenant.created_at == datetime(2026, 3, 1, tzinfo=UTC)
        assert tenant.enabled is True  # default

    def test_tenant_with_quotas(self) -> None:
        """Tenant can specify tier-specific quotas."""
        tenant = Tenant(
            tenant_id="tenant-pro",
            name="Pro Tenant",
            email="pro@example.com",
            tier=TenantTier.PRO,
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
            max_aoi_count=100,
            max_imagery_gb_per_month=500,
        )
        assert tenant.max_aoi_count == 100
        assert tenant.max_imagery_gb_per_month == 500

    def test_tenant_disabled(self) -> None:
        """Tenant can be marked disabled."""
        tenant = Tenant(
            tenant_id="tenant-disabled",
            name="Disabled Tenant",
            email="disabled@example.com",
            tier=TenantTier.FREE,
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
            enabled=False,
        )
        assert tenant.enabled is False

    def test_tenant_serialization(self) -> None:
        """Tenant serializes to dict for Cosmos DB."""
        tenant = Tenant(
            tenant_id="tenant-001",
            name="Test Tenant",
            email="test@example.com",
            tier=TenantTier.FREE,
            created_at=datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC),
        )
        doc = tenant.model_dump()
        assert doc["tenant_id"] == "tenant-001"
        assert doc["tier"] == "free"
        assert "created_at" in doc


class TestJob(unittest.TestCase):
    """Job model (Cosmos DB jobs container)."""

    def test_minimal_job_creation(self) -> None:
        """Job can be created with minimal required fields."""
        job = Job(
            job_id="job-001",
            tenant_id="tenant-001",
            kml_filename="orchard.kml",
            status=JobStatus.PENDING,
            started_at=datetime(2026, 3, 6, 10, 0, 0, tzinfo=UTC),
        )
        assert job.job_id == "job-001"
        assert job.tenant_id == "tenant-001"
        assert job.kml_filename == "orchard.kml"
        assert job.status == JobStatus.PENDING
        assert job.started_at == datetime(2026, 3, 6, 10, 0, 0, tzinfo=UTC)
        assert job.completed_at is None

    def test_job_completed(self) -> None:
        """Job can transition to completed with timestamp."""
        job = Job(
            job_id="job-002",
            tenant_id="tenant-001",
            kml_filename="test.kml",
            status=JobStatus.COMPLETED,
            started_at=datetime(2026, 3, 6, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 3, 6, 10, 5, 30, tzinfo=UTC),
        )
        assert job.status == JobStatus.COMPLETED
        assert job.completed_at is not None

    def test_job_failed_with_error(self) -> None:
        """Job can record failure with error message."""
        job = Job(
            job_id="job-003",
            tenant_id="tenant-001",
            kml_filename="bad.kml",
            status=JobStatus.FAILED,
            started_at=datetime(2026, 3, 6, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 3, 6, 10, 1, 0, tzinfo=UTC),
            error_message="Invalid KML: missing coordinates",
        )
        assert job.status == JobStatus.FAILED
        assert job.error_message == "Invalid KML: missing coordinates"

    def test_job_with_feature_count(self) -> None:
        """Job can track number of features processed."""
        job = Job(
            job_id="job-004",
            tenant_id="tenant-001",
            kml_filename="multi-feature.kml",
            status=JobStatus.COMPLETED,
            started_at=datetime(2026, 3, 6, 10, 0, 0, tzinfo=UTC),
            completed_at=datetime(2026, 3, 6, 10, 10, 0, tzinfo=UTC),
            feature_count=12,
        )
        assert job.feature_count == 12

    def test_job_serialization(self) -> None:
        """Job serializes to dict for Cosmos DB."""
        job = Job(
            job_id="job-001",
            tenant_id="tenant-001",
            kml_filename="test.kml",
            status=JobStatus.RUNNING,
            started_at=datetime(2026, 3, 6, 10, 0, 0, tzinfo=UTC),
        )
        doc = job.model_dump()
        assert doc["job_id"] == "job-001"
        assert doc["tenant_id"] == "tenant-001"
        assert doc["status"] == "running"
        assert "started_at" in doc


class TestTenantTier(unittest.TestCase):
    """TenantTier enum values."""

    def test_tier_values(self) -> None:
        """Tier enum has expected values."""
        assert TenantTier.FREE.value == "free"
        assert TenantTier.PRO.value == "pro"
        assert TenantTier.ENTERPRISE.value == "enterprise"


class TestJobStatus(unittest.TestCase):
    """JobStatus enum values."""

    def test_status_values(self) -> None:
        """Status enum has expected values."""
        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.COMPLETED.value == "completed"
        assert JobStatus.FAILED.value == "failed"

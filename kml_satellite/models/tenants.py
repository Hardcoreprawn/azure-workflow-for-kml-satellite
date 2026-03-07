"""Tenant and job models for Cosmos DB multi-tenant data layer.

Phase 5 #71: Cosmos DB data layer (tenants + jobs containers).

This module defines the Pydantic models for:
- Tenant documents (tenants container, partition key: /tenant_id)
- Job documents (jobs container, partition key: /tenant_id)

References:
    PID § 7.6 (Tenant State - Cosmos DB schema)
    PID FR-9.5 (Cosmos DB with tenant_id partition key)
    ARCHITECTURE_REVIEW § 4.2 (Cosmos DB Data Layer)
    ROADMAP Phase 5 #71 (Cosmos DB setup - tenants + jobs only)
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TenantTier(StrEnum):
    """Subscription tier for tenant quota enforcement.

    Phase 6 will add billing integration (Stripe); for now these are
    operator-assigned labels that govern quota limits.

    Attributes:
        FREE: Limited AOI count, imagery GB, no SLA.
        PRO: Higher limits, faster processing, email support.
        ENTERPRISE: Custom limits, dedicated capacity, phone/Slack support.
    """

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Tenant(BaseModel):
    """Tenant document (tenants container).

    Stores tenant profile, subscription tier, and quota limits.
    Partition key: tenant_id.

    Phase 5 fields: identity, tier, quotas, enabled flag.
    Phase 6 additions: billing_customer_id, subscription_id.
    Phase 7 additions: usage counters (moved from separate usage container).

    Margaret Hamilton principle:
    - tenant_id is immutable primary key (cannot be changed after creation)
    - enabled flag allows operator to disable tenant without deletion
    - created_at is required for audit trail
    """

    tenant_id: str = Field(
        ...,
        description="Immutable tenant identifier (e.g., 'tenant-uuid'). "
        "Used as Cosmos DB partition key and blob container prefix.",
    )
    name: str = Field(..., description="Tenant display name (e.g., 'Acme Orchards')")
    email: str = Field(..., description="Primary contact email")
    tier: TenantTier = Field(..., description="Subscription tier for quota enforcement")
    created_at: datetime = Field(..., description="Tenant registration timestamp (UTC)")
    enabled: bool = Field(
        default=True,
        description="Operator-controlled flag. Disabled tenants cannot upload KML "
        "or process imagery.",
    )

    # Quota limits (tier-specific, enforced by API layer in Phase 6)
    max_aoi_count: int | None = Field(
        default=None,
        description="Maximum number of AOIs (KML features) tenant can track. "
        "None = unlimited (Enterprise tier).",
    )
    max_imagery_gb_per_month: int | None = Field(
        default=None,
        description="Maximum GB of imagery downloads per calendar month. "
        "None = unlimited (Enterprise tier).",
    )

    # Phase 6 fields (not yet used):
    # billing_customer_id: str | None = None
    # subscription_id: str | None = None

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()},
    )


class JobStatus(StrEnum):
    """Pipeline execution status for job tracking.

    Jobs represent a single KML upload → imagery acquisition → analysis cycle.
    Orchestrator instances update the job document as they progress.

    Attributes:
        PENDING: Job created, orchestrator not yet started.
        RUNNING: Orchestrator active (AOI prep / imagery acquisition in progress).
        COMPLETED: All features processed successfully.
        FAILED: Pipeline encountered fatal error (see error_message).
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    """Job document (jobs container).

    Tracks a single KML processing job from upload to completion.
    Partition key: tenant_id.

    Orchestrator writes job_id, status, started_at on ingress.
    Updates status → RUNNING after AOI prep.
    Updates status → COMPLETED/FAILED with completed_at on termination.

    Phase 5: Basic job tracking (status, timestamps, error).
    Phase 7: Add acquisition_count, ndvi_computed fields.

    Margaret Hamilton principle:
    - job_id is deterministic (derived from blob event or orchestration instance ID)
    - tenant_id is required and immutable (cannot be changed after creation)
    - started_at is required for audit (never null)
    - completed_at is null until terminal state reached
    """

    job_id: str = Field(
        ...,
        description="Unique job identifier (e.g., orchestration instance ID or "
        "blob event correlation ID).",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant owning this job. Cosmos DB partition key.",
    )
    kml_filename: str = Field(
        ...,
        description="Original KML blob name (e.g., 'orchard-blocks.kml').",
    )
    status: JobStatus = Field(..., description="Current pipeline execution status")
    started_at: datetime = Field(..., description="Job creation timestamp (UTC)")
    completed_at: datetime | None = Field(
        default=None,
        description="Job termination timestamp (UTC). Null while status=PENDING/RUNNING.",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable error description if status=FAILED.",
    )

    # Optional metadata (populated during execution)
    feature_count: int | None = Field(
        default=None,
        description="Number of KML features extracted (after AOI prep).",
    )

    # Phase 7 additions (not yet used):
    # acquisition_count: int | None = None
    # ndvi_computed: bool = False

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()},
    )

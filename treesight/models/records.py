"""Pydantic models for Cosmos container documents (#583).

Defines typed schemas for:
- RunRecord — ``runs`` container
- SubscriptionRecord — ``subscriptions`` container
- UserRecord — ``users`` container
- EnrichmentManifest — ``timelapse_payload.json`` blob
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# RunRecord — ``runs`` container
# ---------------------------------------------------------------------------


class RunRecord(BaseModel):
    """A pipeline run stored in the Cosmos ``runs`` container.

    Written at submission time and enriched as the pipeline progresses.
    Existing documents may lack optional fields — all non-core fields
    default to ``None`` so reads never break.
    """

    submission_id: str
    instance_id: str
    user_id: str
    submitted_at: str
    kml_blob_name: str = ""
    kml_size_bytes: int = 0
    submission_prefix: str = "analysis"
    provider_name: str = "planetary_computer"
    status: str = "submitted"
    eudr_mode: bool = False

    # Submission context (merged from preflight)
    feature_count: int | None = None
    aoi_count: int | None = None
    max_spread_km: float | None = None
    total_area_ha: float | None = None
    largest_area_ha: float | None = None
    processing_mode: str | None = None
    workspace_role: str | None = None
    workspace_preference: str | None = None

    # Timing (deliverable 5)
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None

    # Billing ledger fields (#589)
    tier_at_submission: str | None = None
    billing_type: str | None = None  # included | overage | free | demo
    overage_unit_price: float | None = None
    billing_status: str | None = None  # pending | charged | refunded
    payment_ref: str | None = None  # external ID from payment provider
    refund_reason: str | None = None  # reason recorded when a charge is refunded

    # Resource consumption (#666)
    resource_summary: dict[str, Any] | None = None
    estimated_cost_pence: float | None = None
    wasted_cost_pence: float | None = None
    # Set if run is refunded or failed after partial resource use.

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# SubscriptionRecord — ``subscriptions`` container
# ---------------------------------------------------------------------------


class SubscriptionRecord(BaseModel):
    """A billing subscription stored in the Cosmos ``subscriptions`` container.

    Two document variants share this container:
    - ``id == user_id``: the real subscription
    - ``id == "{user_id}:emulation"``: local tier override for testing
    """

    user_id: str
    tier: str = "free"
    status: str = "none"
    updated_at: str | None = None

    # Emulation variant fields
    enabled: bool | None = None

    # Stripe fields (present after Stripe webhook)
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# UserRecord — ``users`` container
# ---------------------------------------------------------------------------


class QuotaState(BaseModel):
    """Embedded quota tracking within a user document."""

    runs_used: int = 0
    period_start: str | None = None

    model_config = ConfigDict(extra="allow")


class UserRecord(BaseModel):
    """A user profile stored in the Cosmos ``users`` container.

    Upserted on every sign-in via ``record_user_sign_in()``.
    """

    user_id: str
    email: str = ""
    display_name: str = ""
    identity_provider: str = ""
    billing_allowed: bool = False
    first_seen: str | None = None
    last_seen: str | None = None
    last_modified: str | None = None
    assigned_tier: str | None = None
    org_id: str | None = None
    org_role: str | None = None
    quota: QuotaState | None = None

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# OrgMember — embedded in OrgRecord
# ---------------------------------------------------------------------------


class OrgMember(BaseModel):
    """A member entry within an organisation document."""

    user_id: str
    email: str = ""
    role: str = "member"  # "owner" or "member"
    joined_at: str | None = None

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# OrgRecord — ``orgs`` container
# ---------------------------------------------------------------------------


class OrgRecord(BaseModel):
    """An organisation stored in the Cosmos ``orgs`` container."""

    org_id: str
    name: str = "My Organisation"
    created_by: str = ""
    created_at: str | None = None
    members: list[OrgMember] = Field(default_factory=list)
    billing: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# OrgInvite — ``orgs`` container (invite variant)
# ---------------------------------------------------------------------------


class OrgInvite(BaseModel):
    """A pending org invite stored alongside org docs."""

    org_id: str
    email: str
    invited_by: str = ""
    invited_at: str | None = None
    expires_at: str | None = None

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# EnrichmentManifest — ``timelapse_payload.json``
# ---------------------------------------------------------------------------


class FramePlanEntry(BaseModel):
    """A single frame in the enrichment frame plan."""

    start: str
    end: str
    label: str = ""

    model_config = ConfigDict(extra="allow")


class EnrichmentManifest(BaseModel):
    """Schema for the ``timelapse_payload.json`` enrichment manifest.

    Accumulated across enrichment runner phases.  All fields are optional
    except ``coords`` and ``bbox`` because partial manifests are valid
    (e.g. when no frames match date filters).
    """

    coords: list[list[float]] = Field(default_factory=list)
    bbox: list[float] = Field(default_factory=list)
    center: dict[str, float] | None = None
    frame_plan: list[FramePlanEntry] = Field(default_factory=list)

    # Weather
    weather_daily: list[dict[str, Any]] | None = None

    # NDVI
    ndvi_stats: list[dict[str, Any]] | None = None
    ndvi_raster_paths: list[str] | None = None

    # Change detection
    change_detection: dict[str, Any] | None = None

    # Per-AOI metrics
    per_aoi_metrics: list[dict[str, Any]] | None = None
    multi_aoi_summary: dict[str, Any] | None = None

    # Timing
    enriched_at: str | None = None
    enrichment_duration_seconds: float | None = None
    manifest_path: str | None = None

    # EUDR
    eudr_mode: bool = False
    eudr_date_start: str | None = None

    model_config = ConfigDict(extra="allow")

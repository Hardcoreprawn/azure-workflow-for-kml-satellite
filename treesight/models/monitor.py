"""Monitoring subscription model for scheduled AOI re-analysis (§3.1).

A monitor tracks a single AOI for periodic NDVI change detection,
comparing each run against a stored baseline and alerting when
user-configured thresholds are breached.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AlertThresholds(BaseModel):
    """User-configurable thresholds that trigger email alerts."""

    loss_pct: float = 5.0
    gain_pct: float | None = None
    ndvi_mean_drop: float = 0.1


class MonitorRecord(BaseModel):
    """Persistent monitoring subscription for a single AOI.

    Stored in the ``monitors`` Cosmos container (partition key ``/user_id``).
    """

    id: str
    user_id: str
    aoi_name: str
    source_file: str = ""
    aoi_geometry: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    cadence_days: int = 30
    next_check_at: datetime | None = None
    baseline_run_id: str | None = None
    baseline_ndvi_mean: float | None = None
    last_run_id: str | None = None
    last_run_at: datetime | None = None
    alert_thresholds: AlertThresholds = Field(default_factory=AlertThresholds)
    alert_email: str = ""
    alert_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_cosmos(self) -> dict[str, Any]:
        """Serialise for Cosmos DB upsert (datetime → ISO string)."""
        data = self.model_dump(mode="json")
        return data

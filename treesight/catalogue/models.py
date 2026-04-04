"""Cosmos DB document schema for catalogue entries (internal data model).

This is the persistence layer's view of a catalogue entry.  It is NOT
the API contract — see ``contracts.py`` for request/response schemas.

Each document represents a single AOI within a single pipeline run,
capturing the acquisition metadata, NDVI stats, and enrichment results
so that users can query historical analyses per AOI over time.

Container: ``catalogue``  |  Partition key: ``/user_id``
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CatalogueEntry(BaseModel):
    """A single per-AOI acquisition record stored in Cosmos DB.

    The ``id`` is ``{run_id}:{aoi_name_slug}`` to ensure uniqueness
    within a user's partition while allowing multiple AOIs per run.
    """

    # --- Identity ---
    id: str
    user_id: str
    run_id: str
    aoi_name: str

    # --- Source ---
    source_file: str = ""
    provider: str = ""

    # --- Geometry (stored for map display / re-analysis) ---
    centroid: list[float] = Field(default_factory=list)
    bbox: list[float] = Field(default_factory=list)
    area_ha: float = 0.0

    # --- Temporal ---
    acquired_at: datetime | None = None
    submitted_at: datetime | None = None

    # --- Acquisition quality ---
    cloud_cover_pct: float | None = None
    spatial_resolution_m: float | None = None
    collection: str = ""

    # --- Results ---
    status: str = "pending"
    ndvi_mean: float | None = None
    ndvi_min: float | None = None
    ndvi_max: float | None = None
    change_loss_pct: float | None = None
    change_gain_pct: float | None = None
    change_mean_delta: float | None = None

    # --- Artifacts ---
    imagery_blob_path: str = ""
    metadata_blob_path: str = ""
    enrichment_manifest_path: str = ""

    # --- Housekeeping ---
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_cosmos(self) -> dict[str, Any]:
        """Serialise for Cosmos DB upsert (datetime → ISO string)."""
        return self.model_dump(mode="json")

    @classmethod
    def from_cosmos(cls, doc: dict[str, Any]) -> CatalogueEntry:
        """Deserialise a Cosmos document, stripping system properties."""
        clean = {k: v for k, v in doc.items() if not k.startswith("_")}
        return cls(**clean)

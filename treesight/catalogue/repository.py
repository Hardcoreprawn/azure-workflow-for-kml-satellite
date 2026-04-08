"""Catalogue persistence — Cosmos DB repository (§3.2).

All operations work with ``CatalogueEntry`` data models.
The API layer converts to/from contracts; this layer never
imports anything from ``contracts.py``.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from treesight.catalogue.models import CatalogueEntry

logger = logging.getLogger(__name__)

CATALOGUE_CONTAINER = "catalogue"


def _slugify(name: str) -> str:
    """Convert an AOI name to a Cosmos-safe slug for the document id."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80] or "unnamed"


def _make_id(run_id: str, aoi_name: str) -> str:
    """Build a deterministic document id: ``{run_id}:{aoi_slug}``."""
    return f"{run_id}:{_slugify(aoi_name)}"


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


def record_acquisition(
    user_id: str,
    run_id: str,
    aoi_name: str,
    *,
    source_file: str = "",
    provider: str = "",
    centroid: list[float] | None = None,
    bbox: list[float] | None = None,
    area_ha: float = 0.0,
    acquired_at: datetime | None = None,
    submitted_at: datetime | None = None,
    cloud_cover_pct: float | None = None,
    spatial_resolution_m: float | None = None,
    collection: str = "",
    status: str = "completed",
    ndvi_mean: float | None = None,
    ndvi_min: float | None = None,
    ndvi_max: float | None = None,
    change_loss_pct: float | None = None,
    change_gain_pct: float | None = None,
    change_mean_delta: float | None = None,
    imagery_blob_path: str = "",
    metadata_blob_path: str = "",
    enrichment_manifest_path: str = "",
) -> CatalogueEntry:
    """Create or update a catalogue entry for a single AOI acquisition."""
    from treesight.storage.cosmos import upsert_item

    now = datetime.now(UTC)
    doc_id = _make_id(run_id, aoi_name)

    # Preserve created_at if the entry already exists (upsert semantics)
    existing = get_entry(doc_id, user_id)
    created_ts = existing.created_at if existing else now

    entry = CatalogueEntry(
        id=doc_id,
        user_id=user_id,
        run_id=run_id,
        aoi_name=aoi_name,
        source_file=source_file,
        provider=provider,
        centroid=centroid or [],
        bbox=bbox or [],
        area_ha=area_ha,
        acquired_at=acquired_at,
        submitted_at=submitted_at or now,
        cloud_cover_pct=cloud_cover_pct,
        spatial_resolution_m=spatial_resolution_m,
        collection=collection,
        status=status,
        ndvi_mean=ndvi_mean,
        ndvi_min=ndvi_min,
        ndvi_max=ndvi_max,
        change_loss_pct=change_loss_pct,
        change_gain_pct=change_gain_pct,
        change_mean_delta=change_mean_delta,
        imagery_blob_path=imagery_blob_path,
        metadata_blob_path=metadata_blob_path,
        enrichment_manifest_path=enrichment_manifest_path,
        created_at=created_ts,
        updated_at=now,
    )

    upsert_item(CATALOGUE_CONTAINER, entry.to_cosmos())
    logger.info(
        "Catalogue entry recorded id=%s user=%s aoi=%s run=%s",
        entry.id,
        user_id,
        aoi_name,
        run_id,
    )
    return entry


def update_entry(entry: CatalogueEntry) -> CatalogueEntry:
    """Persist an updated catalogue entry."""
    from treesight.storage.cosmos import upsert_item

    entry.updated_at = datetime.now(UTC)
    upsert_item(CATALOGUE_CONTAINER, entry.to_cosmos())
    return entry


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def get_entry(entry_id: str, user_id: str) -> CatalogueEntry | None:
    """Read a single catalogue entry by id and partition key."""
    from treesight.storage.cosmos import read_item

    doc = read_item(CATALOGUE_CONTAINER, entry_id, user_id)
    if not doc:
        return None
    return CatalogueEntry.from_cosmos(doc)


def list_entries(
    user_id: str,
    *,
    aoi_name: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    provider: str | None = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = "desc",
) -> tuple[list[CatalogueEntry], int]:
    """Query catalogue entries with optional filters.

    Returns ``(entries, total_count)``.
    """
    from treesight.storage.cosmos import query_items

    # Build query dynamically — partition_key scopes to user_id already
    conditions: list[str] = []
    params: list[dict[str, Any]] = []

    if aoi_name:
        conditions.append("CONTAINS(LOWER(c.aoi_name), @aoi_name)")
        params.append({"name": "@aoi_name", "value": aoi_name.lower()})

    if status:
        conditions.append("c.status = @status")
        params.append({"name": "@status", "value": status})

    if date_from:
        conditions.append("c.submitted_at >= @date_from")
        params.append({"name": "@date_from", "value": date_from.isoformat()})

    if date_to:
        conditions.append("c.submitted_at <= @date_to")
        params.append({"name": "@date_to", "value": date_to.isoformat()})

    if provider:
        conditions.append("c.provider = @provider")
        params.append({"name": "@provider", "value": provider})

    where_clause = (" AND ".join(conditions)) if conditions else "true"
    order = "DESC" if sort == "desc" else "ASC"

    # Count query for pagination metadata
    count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where_clause}"  # noqa: S608  — Cosmos SQL with parameterised @-bindings, not user-interpolated
    count_result = query_items(
        CATALOGUE_CONTAINER,
        count_query,
        parameters=params,
        partition_key=user_id,
    )
    total: int = int(count_result[0]) if count_result else 0  # type: ignore[arg-type]  # SELECT VALUE returns raw int

    # Data query with pagination
    data_query = (
        f"SELECT * FROM c WHERE {where_clause}"  # noqa: S608  — same parameterised Cosmos SQL as count_query above
        f" ORDER BY c.submitted_at {order}"
        f" OFFSET @off LIMIT @lim"
    )
    data_params = [
        *params,
        {"name": "@off", "value": offset},
        {"name": "@lim", "value": limit},
    ]

    docs = query_items(
        CATALOGUE_CONTAINER,
        data_query,
        parameters=data_params,
        partition_key=user_id,
    )

    entries = [CatalogueEntry.from_cosmos(doc) for doc in docs]
    return entries, total


def list_entries_for_run(
    user_id: str,
    run_id: str,
) -> list[CatalogueEntry]:
    """List all catalogue entries for a specific pipeline run."""
    from treesight.storage.cosmos import query_items

    docs = query_items(
        CATALOGUE_CONTAINER,
        "SELECT * FROM c WHERE c.run_id = @rid ORDER BY c.aoi_name ASC",
        parameters=[
            {"name": "@rid", "value": run_id},
        ],
        partition_key=user_id,
    )
    return [CatalogueEntry.from_cosmos(doc) for doc in docs]


def list_entries_for_aoi(
    user_id: str,
    aoi_name: str,
    *,
    limit: int = 20,
) -> list[CatalogueEntry]:
    """List acquisition history for a specific AOI (time series view)."""
    from treesight.storage.cosmos import query_items

    docs = query_items(
        CATALOGUE_CONTAINER,
        "SELECT * FROM c WHERE c.aoi_name = @aoi ORDER BY c.submitted_at DESC OFFSET 0 LIMIT @lim",
        parameters=[
            {"name": "@aoi", "value": aoi_name},
            {"name": "@lim", "value": limit},
        ],
        partition_key=user_id,
    )
    return [CatalogueEntry.from_cosmos(doc) for doc in docs]

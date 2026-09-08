"""EUDR summary export helpers.

Pure functions for assembling per-AOI CSV rows from run manifests.
No HTTP or Azure Functions dependency.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from treesight.exports.geojson import _aoi_eudr_value
from treesight.pipeline.enrichment.determination import as_screening_determination

SUMMARY_CSV_FIELDS = [
    "run_id",
    "submitted_at",
    "parcel_name",
    "area_ha",
    "center_lat",
    "center_lon",
    "determination_status",
    "determination_confidence",
    "determination_flags",
    "overridden",
    "override_reason",
    "note",
    "reviewer_note",
    "reviewed_by",
    "reviewed_at",
]


def summary_rows_from_manifest(
    run_id: str,
    submitted_at: str,
    manifest: dict[str, Any],
    run_record: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Extract per-AOI CSV rows from a single run manifest + run record annotations."""
    per_aoi = manifest.get("per_aoi_enrichment", [])
    if not per_aoi:
        return []

    parcel_notes: dict[str, str] = {}
    parcel_overrides: dict[str, dict[str, Any]] = {}
    parcel_reviews: dict[str, dict[str, Any]] = {}
    if run_record:
        raw_notes = run_record.get("parcel_notes")
        raw_overrides = run_record.get("parcel_overrides")
        raw_reviews = run_record.get("parcel_reviews")
        parcel_notes = raw_notes if isinstance(raw_notes, dict) else {}
        parcel_overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
        parcel_reviews = raw_reviews if isinstance(raw_reviews, dict) else {}

    rows = []
    for idx, aoi in enumerate(per_aoi):
        parcel_key = str(idx)
        center = aoi.get("center", {})
        determination = as_screening_determination(_aoi_eudr_value(aoi, "determination"))
        raw_override = parcel_overrides.get(parcel_key, {})
        override = raw_override if isinstance(raw_override, dict) else {}
        overridden = bool(override) and not override.get("reverted")
        raw_review = parcel_reviews.get(parcel_key, {})
        review = raw_review if isinstance(raw_review, dict) else {}

        rows.append(
            {
                "run_id": run_id,
                "submitted_at": submitted_at,
                "parcel_name": aoi.get("name", parcel_key),
                "area_ha": aoi.get("area_ha", ""),
                "center_lat": center.get("lat", ""),
                "center_lon": center.get("lon", ""),
                "determination_status": ("error" if "error" in aoi else determination.screening_outcome),
                "determination_confidence": determination.confidence,
                "determination_flags": "; ".join(determination.flags),
                "overridden": "yes" if overridden else "no",
                "override_reason": override.get("reason", "") if overridden else "",
                "note": parcel_notes.get(parcel_key, ""),
                "reviewer_note": review.get("note", ""),
                "reviewed_by": review.get("reviewed_by", ""),
                "reviewed_at": review.get("reviewed_at", ""),
            }
        )
    return rows


def build_summary_csv(rows: list[dict[str, Any]]) -> str:
    """Serialise a list of summary row dicts as a CSV string."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SUMMARY_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()

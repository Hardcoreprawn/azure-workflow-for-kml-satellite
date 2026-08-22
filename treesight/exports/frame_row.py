"""Typed frame row extracted from an enrichment manifest ``frame_plan`` entry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class FrameRow:
    """A single temporal observation frame from the enrichment manifest.

    Both the CSV and GeoJSON builders consume a typed list of ``FrameRow``
    objects rather than reaching into raw dicts, eliminating the duplicated
    field-extraction logic identified in the C4 architecture review.
    """

    frame_index: int
    label: str
    year: int | str
    season: str
    start: str
    end: str
    collection: str
    is_naip: bool
    provenance: dict[str, Any] = field(default_factory=dict)
    ndvi_raster_path: str = ""  # legacy fallback when provenance["artifact_path"] is absent

    @classmethod
    def from_dict(cls, index: int, frame: dict[str, Any]) -> FrameRow:
        """Construct a ``FrameRow`` from a raw frame-plan dict entry."""
        return cls(
            frame_index=index,
            label=frame.get("label", ""),
            year=frame.get("year", ""),
            season=frame.get("season", ""),
            start=frame.get("start", ""),
            end=frame.get("end", ""),
            collection=frame.get("collection", ""),
            is_naip=bool(frame.get("is_naip", False)),
            provenance=frame.get("provenance") or {},
            ndvi_raster_path=frame.get("ndvi_raster_path", ""),
        )

"""Geolocation provenance model — separates legal/source geometry from derived analysis geometry.

Under EUDR Article 2(28), the supplier-declared geolocation is the legal reference.
A buffered or derived polygon used for satellite analysis is not equivalent to a
supplier-declared boundary and must never be exported or described as such.

This model records both geometries and the derivation metadata required for
traceable, auditable EUDR geolocation claims.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class GeometryType(StrEnum):
    """Source geometry type as supplied by the actor."""

    POINT = "Point"
    POLYGON = "Polygon"


class LegalUseClassification(StrEnum):
    """Legal-use classification for EUDR geolocation provenance.

    - ``dds_eligible``: Geometry meets EUDR due-diligence requirements
      (point ≤4 ha, or polygon with area declared).
    - ``incomplete``: Required fields are missing (e.g. area not declared for
      a point without a polygon alternative).
    - ``screening_only``: Geometry is a proxy/catchment that cannot serve as
      legal evidence; satellite analysis use only.
    """

    DDS_ELIGIBLE = "dds_eligible"
    INCOMPLETE = "incomplete"
    SCREENING_ONLY = "screening_only"


class GeolocationProvenance(BaseModel):
    """Separates the legal/source geolocation from derived analysis geometry.

    Attributes
    ----------
    source_geometry_type:
        Geometry type as supplied (Point or Polygon).
    source_geometry:
        Original supplier-declared coordinates.  For a point this is
        ``[lon, lat]``; for a polygon it is a list of ``[lon, lat]`` rings.
        This field is immutable — it must never be replaced by a derived shape.
    derived_geometry:
        Analysis footprint (e.g. buffer polygon).  May be None if the source
        is already a polygon.
    derivation_method:
        Short label describing how ``derived_geometry`` was produced, e.g.
        ``"point_buffer_circle"``.  Empty string when no derivation was applied.
    derivation_params:
        Free-form parameters used in the derivation (e.g.
        ``{"radius_m": 100, "segments": 32}``).
    source_actor:
        Organisation or individual who supplied the geolocation.
    source_document:
        Reference document or dataset from which the coordinates originate.
    capture_method:
        How the coordinates were captured, e.g. ``"GPS"``, ``"survey"``,
        ``"digitised"``.
    capture_date:
        Date on which the coordinates were captured.
    positional_accuracy_m:
        Estimated positional accuracy in metres.  None if unknown.
    positional_verifier:
        Party or system that verified positional accuracy.
    plot_area_ha:
        Declared plot area in hectares.  None if not declared.
    polygon_required:
        True when a polygon is legally required (plot > 4 ha under EUDR
        Article 2(28)) but only a point was supplied.
    legal_use_classification:
        Whether this provenance record is ``dds_eligible``, ``incomplete``,
        or ``screening_only``.
    """

    source_geometry_type: GeometryType
    source_geometry: list[Any] = Field(
        description="Original supplier-declared geometry coordinates (immutable)."
    )
    derived_geometry: list[list[float]] | None = Field(
        default=None,
        description="Analysis footprint derived from the source geometry.",
    )
    derivation_method: str = Field(
        default="",
        description="Method used to derive analysis geometry from source.",
    )
    derivation_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters used in the derivation step.",
    )
    source_actor: str = ""
    source_document: str = ""
    capture_method: str = ""
    capture_date: date | None = None
    positional_accuracy_m: float | None = None
    positional_verifier: str = ""
    plot_area_ha: float | None = None
    polygon_required: bool = False
    legal_use_classification: LegalUseClassification = LegalUseClassification.INCOMPLETE

    model_config = {"frozen": True}

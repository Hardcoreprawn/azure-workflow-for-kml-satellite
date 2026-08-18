"""PDF export builders — re-exported from ``treesight.exports.pdf`` (M4 §4.6).

Import from this module for backward compatibility; logic lives in the
domain package ``treesight/exports/pdf.py``.
"""

from treesight.exports.pdf import (
    _build_pdf,
    _pdf_eudr_section,
    _pdf_header,
    _pdf_per_parcel_sections,
    _pdf_scene_provenance_section,
    _pdf_vegetation_section,
    _safe_text,
)

__all__ = [
    "_build_pdf",
    "_pdf_eudr_section",
    "_pdf_header",
    "_pdf_per_parcel_sections",
    "_pdf_scene_provenance_section",
    "_pdf_vegetation_section",
    "_safe_text",
]

"""Audit-grade EUDR PDF builder — re-exported from ``treesight.exports.pdf_audit`` (M4 §4.6).

Import from this module for backward compatibility; logic lives in the
domain package ``treesight/exports/pdf_audit.py``.
"""

from treesight.exports.pdf_audit import (
    _render_parcel_review_section,
    build_eudr_audit_pdf,
)

__all__ = ["_render_parcel_review_section", "build_eudr_audit_pdf"]

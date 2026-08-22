"""Domain-level export renderers — format → renderer registry.

Each renderer takes a typed manifest dict plus optional options and returns
a Python object (bytes or dict/str) with no HTTP types present.

The HTTP dispatch shell in ``blueprints/export/__init__.py`` calls into
this package; the renderers themselves are independently unit-testable.
"""

from __future__ import annotations

from treesight.exports.frame_row import FrameRow
from treesight.exports.pdf_audit import build_eudr_audit_pdf

__all__ = [
    "FrameRow",
    "build_eudr_audit_pdf",
]

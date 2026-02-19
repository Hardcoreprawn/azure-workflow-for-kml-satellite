"""Shared pipeline constants — single source of truth.

Centralises container names, path prefixes, and other string literals
that were previously duplicated across activities, providers, and the
orchestrator.

References:
    PID Section 10.1  (Container & Path Layout)
    PID 7.4.5         (Explicit — named constants, no magic strings)
    Issue #52          (Centralise shared pipeline constants)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Blob container names (PID Section 10.1)
# ---------------------------------------------------------------------------

INPUT_CONTAINER: str = "kml-input"
"""Blob container for incoming KML files."""

OUTPUT_CONTAINER: str = "kml-output"
"""Blob container for all pipeline outputs (imagery, metadata, KML archive)."""

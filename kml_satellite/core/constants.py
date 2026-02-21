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

DEFAULT_INPUT_CONTAINER: str = "kml-input"
"""Default blob container for incoming KML files."""

DEFAULT_OUTPUT_CONTAINER: str = "kml-output"
"""Default blob container for all pipeline outputs (imagery, metadata, KML archive)."""


def resolve_tenant_containers(container_name: str) -> tuple[str, str, str]:
    """Resolve tenant context from a container name.

    Args:
        container_name: The input container name (e.g. "acme-input" or "kml-input").

    Returns:
        Tuple of (tenant_id, input_container, output_container).
        For legacy "kml-input", returns ("", "kml-input", "kml-output").
    """
    if container_name.endswith("-input"):
        prefix = container_name[: -len("-input")]
        if prefix == "kml":
            return ("", DEFAULT_INPUT_CONTAINER, DEFAULT_OUTPUT_CONTAINER)
        return (prefix, container_name, f"{prefix}-output")
    return ("", DEFAULT_INPUT_CONTAINER, DEFAULT_OUTPUT_CONTAINER)

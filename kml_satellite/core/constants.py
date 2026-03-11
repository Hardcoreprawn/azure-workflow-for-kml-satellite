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

PIPELINE_PAYLOADS_CONTAINER: str = "pipeline-payloads"
"""Container used for offloaded payloads and lightweight operational captures."""


# ---------------------------------------------------------------------------
# Numeric defaults and bounds
# ---------------------------------------------------------------------------

KIBIBYTE: int = 1024
MEBIBYTE: int = 1024 * KIBIBYTE

MAX_KML_FILE_SIZE_BYTES: int = 10 * MEBIBYTE
"""Maximum allowed KML payload size at ingress (10 MiB)."""

PAYLOAD_OFFLOAD_THRESHOLD_BYTES: int = 48 * KIBIBYTE
"""Durable history offload threshold for compact JSON payloads."""

DEFAULT_IMAGERY_RESOLUTION_TARGET_M: float = 0.5
DEFAULT_IMAGERY_MAX_CLOUD_COVER_PCT: float = 20.0
DEFAULT_AOI_BUFFER_M: float = 100.0
DEFAULT_AOI_MAX_AREA_HA: float = 10_000.0

MIN_PERCENTAGE: float = 0.0
MAX_PERCENTAGE: float = 100.0

DEFAULT_MAX_OFF_NADIR_DEG: float = 30.0
MAX_OFF_NADIR_DEG_LIMIT: float = 90.0

MIN_RESOLUTION_M: float = 0.0
DEFAULT_MAX_RESOLUTION_M: float = 50.0


# ---------------------------------------------------------------------------
# Provider adapter constants
# ---------------------------------------------------------------------------

STAC_SEARCH_MAX_ITEMS: int = 50
"""Maximum items to retrieve from STAC search (Planetary Computer)."""

STAC_ITEM_FETCH_MAX_ITEMS: int = 1
"""Maximum items for single item fetch by ID (should always be 1)."""

HTTP_DOWNLOAD_TIMEOUT_SECONDS: float = 60.0
"""Timeout for HTTP imagery downloads from provider APIs."""


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

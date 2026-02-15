"""Pipeline configuration loaded from environment variables.

All configuration values have sensible defaults aligned with the PID.
Azure Functions app settings (or ``local.settings.json`` for local dev)
are the source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Immutable pipeline configuration.

    Loaded once at function startup and threaded through the orchestrator.

    Attributes:
        kml_input_container: Blob container for incoming KML files.
        kml_output_container: Blob container for processed outputs.
        imagery_provider: Active imagery provider (``planetary_computer`` or ``skywatch``).
        imagery_resolution_target_m: Target spatial resolution in metres.
        imagery_max_cloud_cover_pct: Maximum acceptable cloud cover percentage.
        aoi_buffer_m: Buffer distance in metres applied to each polygon's bounding box.
        aoi_max_area_ha: Area threshold (ha) above which a warning is logged.
        keyvault_url: Azure Key Vault URI (empty when running locally).
    """

    kml_input_container: str = "kml-input"
    kml_output_container: str = "kml-output"
    imagery_provider: str = "planetary_computer"
    imagery_resolution_target_m: float = 0.5
    imagery_max_cloud_cover_pct: float = 20.0
    aoi_buffer_m: float = 100.0
    aoi_max_area_ha: float = 10_000.0
    keyvault_url: str = ""

    @classmethod
    def from_env(cls) -> PipelineConfig:
        """Load configuration from environment variables.

        Environment variable names match the keys in
        ``local.settings.json.template``.
        """
        return cls(
            kml_input_container=os.getenv("KML_INPUT_CONTAINER", "kml-input"),
            kml_output_container=os.getenv("KML_OUTPUT_CONTAINER", "kml-output"),
            imagery_provider=os.getenv("IMAGERY_PROVIDER", "planetary_computer"),
            imagery_resolution_target_m=float(os.getenv("IMAGERY_RESOLUTION_TARGET_M", "0.5")),
            imagery_max_cloud_cover_pct=float(os.getenv("IMAGERY_MAX_CLOUD_COVER_PCT", "20")),
            aoi_buffer_m=float(os.getenv("AOI_BUFFER_M", "100")),
            aoi_max_area_ha=float(os.getenv("AOI_MAX_AREA_HA", "10000")),
            keyvault_url=os.getenv("KEYVAULT_URL", ""),
        )

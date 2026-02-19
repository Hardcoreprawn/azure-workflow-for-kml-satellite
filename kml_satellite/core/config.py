"""Pipeline configuration loaded from environment variables.

All configuration values have sensible defaults aligned with the PID.
Azure Functions app settings (or ``local.settings.json`` for local dev)
are the source of truth.

Fail-fast validation (Issue #48):
    ``from_env()`` raises ``ConfigValidationError`` if any numeric
    value is out of its valid range.  This prevents latent runtime
    errors by catching bad configuration at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from kml_satellite.core.exceptions import PipelineError


class ConfigValidationError(PipelineError):
    """Raised when configuration values are out of valid range.

    Attributes:
        key: The configuration key that failed validation.
        value: The invalid value.
        message: Human-readable description of the valid range.
    """

    default_stage = "config"
    default_code = "CONFIG_VALIDATION_FAILED"

    def __init__(self, key: str, value: object, message: str) -> None:
        self.key = key
        self.value = value
        self.message = message
        super().__init__(f"Invalid configuration {key}={value!r}: {message}")


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
        """Load and validate configuration from environment variables.

        Environment variable names match the keys in
        ``local.settings.json.template``.

        Raises:
            ConfigValidationError: If a numeric value is out of range
                or a required string value is empty.
            ValueError: If a numeric environment variable cannot be
                parsed (e.g. ``AOI_BUFFER_M=abc``).
        """
        config = cls(
            kml_input_container=os.getenv("KML_INPUT_CONTAINER", "kml-input"),
            kml_output_container=os.getenv("KML_OUTPUT_CONTAINER", "kml-output"),
            imagery_provider=os.getenv("IMAGERY_PROVIDER", "planetary_computer"),
            imagery_resolution_target_m=float(os.getenv("IMAGERY_RESOLUTION_TARGET_M", "0.5")),
            imagery_max_cloud_cover_pct=float(os.getenv("IMAGERY_MAX_CLOUD_COVER_PCT", "20")),
            aoi_buffer_m=float(os.getenv("AOI_BUFFER_M", "100")),
            aoi_max_area_ha=float(os.getenv("AOI_MAX_AREA_HA", "10000")),
            keyvault_url=os.getenv("KEYVAULT_URL", ""),
        )
        _validate(config)
        return config


def _validate(config: PipelineConfig) -> None:
    """Validate configuration ranges.  Raises ``ConfigValidationError``."""
    if config.imagery_resolution_target_m <= 0:
        raise ConfigValidationError(
            "IMAGERY_RESOLUTION_TARGET_M",
            config.imagery_resolution_target_m,
            "must be > 0 (metres)",
        )

    if not 0.0 <= config.imagery_max_cloud_cover_pct <= 100.0:
        raise ConfigValidationError(
            "IMAGERY_MAX_CLOUD_COVER_PCT",
            config.imagery_max_cloud_cover_pct,
            "must be between 0 and 100 (percentage)",
        )

    if config.aoi_buffer_m < 0:
        raise ConfigValidationError(
            "AOI_BUFFER_M",
            config.aoi_buffer_m,
            "must be >= 0 (metres)",
        )

    if config.aoi_max_area_ha <= 0:
        raise ConfigValidationError(
            "AOI_MAX_AREA_HA",
            config.aoi_max_area_ha,
            "must be > 0 (hectares)",
        )

    if not config.kml_input_container:
        raise ConfigValidationError(
            "KML_INPUT_CONTAINER",
            config.kml_input_container,
            "must not be empty",
        )

    if not config.kml_output_container:
        raise ConfigValidationError(
            "KML_OUTPUT_CONTAINER",
            config.kml_output_container,
            "must not be empty",
        )

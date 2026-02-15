"""Tests for pipeline configuration.

Covers:
- Default values match PID and local.settings.json.template
- Loading from environment variables
- Type coercion (string env vars → numeric fields)
"""

from __future__ import annotations

import os
from unittest.mock import patch

from kml_satellite.core.config import PipelineConfig


class TestPipelineConfigDefaults:
    """Verify default configuration values."""

    def test_default_containers(self) -> None:
        cfg = PipelineConfig()
        assert cfg.kml_input_container == "kml-input"
        assert cfg.kml_output_container == "kml-output"

    def test_default_imagery_provider(self) -> None:
        cfg = PipelineConfig()
        assert cfg.imagery_provider == "planetary_computer"

    def test_default_resolution(self) -> None:
        cfg = PipelineConfig()
        assert cfg.imagery_resolution_target_m == 0.5

    def test_default_cloud_cover(self) -> None:
        cfg = PipelineConfig()
        assert cfg.imagery_max_cloud_cover_pct == 20.0

    def test_default_aoi_buffer(self) -> None:
        cfg = PipelineConfig()
        assert cfg.aoi_buffer_m == 100.0

    def test_default_max_area(self) -> None:
        cfg = PipelineConfig()
        assert cfg.aoi_max_area_ha == 10_000.0

    def test_default_keyvault_url(self) -> None:
        cfg = PipelineConfig()
        assert cfg.keyvault_url == ""


class TestPipelineConfigFromEnv:
    """Verify loading from environment variables."""

    def test_loads_from_environment(self) -> None:
        """All env vars are read and coerced to correct types."""
        env = {
            "KML_INPUT_CONTAINER": "custom-input",
            "KML_OUTPUT_CONTAINER": "custom-output",
            "IMAGERY_PROVIDER": "skywatch",
            "IMAGERY_RESOLUTION_TARGET_M": "2.0",
            "IMAGERY_MAX_CLOUD_COVER_PCT": "30",
            "AOI_BUFFER_M": "150",
            "AOI_MAX_AREA_HA": "5000",
            "KEYVAULT_URL": "https://kv-test.vault.azure.net/",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = PipelineConfig.from_env()

        assert cfg.kml_input_container == "custom-input"
        assert cfg.kml_output_container == "custom-output"
        assert cfg.imagery_provider == "skywatch"
        assert cfg.imagery_resolution_target_m == 2.0
        assert cfg.imagery_max_cloud_cover_pct == 30.0
        assert cfg.aoi_buffer_m == 150.0
        assert cfg.aoi_max_area_ha == 5000.0
        assert cfg.keyvault_url == "https://kv-test.vault.azure.net/"

    def test_defaults_when_env_missing(self) -> None:
        """Missing environment variables fall back to defaults."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = PipelineConfig.from_env()

        assert cfg.kml_input_container == "kml-input"
        assert cfg.imagery_provider == "planetary_computer"
        assert cfg.aoi_buffer_m == 100.0

    def test_frozen_immutability(self) -> None:
        """PipelineConfig is frozen (immutable)."""
        cfg = PipelineConfig()
        try:
            cfg.aoi_buffer_m = 200.0  # type: ignore[misc]
            raise AssertionError("Expected AttributeError")
        except AttributeError:
            pass  # Expected

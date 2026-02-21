"""Tests for pipeline configuration.

Covers:
- Default values match PID and local.settings.json.template
- Loading from environment variables
- Type coercion (string env vars → numeric fields)
- Fail-fast range validation (Issue #48)
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from kml_satellite.core.config import ConfigValidationError, PipelineConfig


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
        with pytest.raises(AttributeError):
            cfg.aoi_buffer_m = 200.0  # type: ignore[misc]


class TestPipelineConfigValidation:
    """Fail-fast range validation in from_env (Issue #48)."""

    def test_valid_defaults_pass(self) -> None:
        """Default configuration passes all validation checks."""
        with patch.dict(os.environ, {}, clear=True):
            cfg = PipelineConfig.from_env()
        assert cfg.aoi_buffer_m == 100.0

    def test_resolution_zero_rejected(self) -> None:
        """Resolution <= 0 → ConfigValidationError."""
        with (
            patch.dict(os.environ, {"IMAGERY_RESOLUTION_TARGET_M": "0"}, clear=True),
            pytest.raises(ConfigValidationError, match="IMAGERY_RESOLUTION_TARGET_M"),
        ):
            PipelineConfig.from_env()

    def test_resolution_negative_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"IMAGERY_RESOLUTION_TARGET_M": "-1"}, clear=True),
            pytest.raises(ConfigValidationError, match="must be > 0"),
        ):
            PipelineConfig.from_env()

    def test_resolution_positive_accepted(self) -> None:
        with patch.dict(os.environ, {"IMAGERY_RESOLUTION_TARGET_M": "0.3"}, clear=True):
            cfg = PipelineConfig.from_env()
        assert cfg.imagery_resolution_target_m == 0.3

    def test_cloud_cover_negative_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"IMAGERY_MAX_CLOUD_COVER_PCT": "-1"}, clear=True),
            pytest.raises(ConfigValidationError, match="IMAGERY_MAX_CLOUD_COVER_PCT"),
        ):
            PipelineConfig.from_env()

    def test_cloud_cover_over_100_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"IMAGERY_MAX_CLOUD_COVER_PCT": "101"}, clear=True),
            pytest.raises(ConfigValidationError, match="0 and 100"),
        ):
            PipelineConfig.from_env()

    def test_cloud_cover_boundary_0_accepted(self) -> None:
        with patch.dict(os.environ, {"IMAGERY_MAX_CLOUD_COVER_PCT": "0"}, clear=True):
            cfg = PipelineConfig.from_env()
        assert cfg.imagery_max_cloud_cover_pct == 0.0

    def test_cloud_cover_boundary_100_accepted(self) -> None:
        with patch.dict(os.environ, {"IMAGERY_MAX_CLOUD_COVER_PCT": "100"}, clear=True):
            cfg = PipelineConfig.from_env()
        assert cfg.imagery_max_cloud_cover_pct == 100.0

    def test_buffer_negative_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"AOI_BUFFER_M": "-10"}, clear=True),
            pytest.raises(ConfigValidationError, match="AOI_BUFFER_M"),
        ):
            PipelineConfig.from_env()

    def test_buffer_zero_accepted(self) -> None:
        """Buffer of 0 metres is valid (no buffer)."""
        with patch.dict(os.environ, {"AOI_BUFFER_M": "0"}, clear=True):
            cfg = PipelineConfig.from_env()
        assert cfg.aoi_buffer_m == 0.0

    def test_max_area_zero_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"AOI_MAX_AREA_HA": "0"}, clear=True),
            pytest.raises(ConfigValidationError, match="AOI_MAX_AREA_HA"),
        ):
            PipelineConfig.from_env()

    def test_max_area_negative_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"AOI_MAX_AREA_HA": "-100"}, clear=True),
            pytest.raises(ConfigValidationError, match="must be > 0"),
        ):
            PipelineConfig.from_env()

    def test_empty_input_container_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"KML_INPUT_CONTAINER": ""}, clear=True),
            pytest.raises(ConfigValidationError, match="KML_INPUT_CONTAINER"),
        ):
            PipelineConfig.from_env()

    def test_empty_output_container_rejected(self) -> None:
        with (
            patch.dict(os.environ, {"KML_OUTPUT_CONTAINER": ""}, clear=True),
            pytest.raises(ConfigValidationError, match="KML_OUTPUT_CONTAINER"),
        ):
            PipelineConfig.from_env()

    def test_non_numeric_env_raises_value_error(self) -> None:
        """Non-numeric string for a float field → ValueError."""
        with (
            patch.dict(os.environ, {"AOI_BUFFER_M": "abc"}, clear=True),
            pytest.raises(ValueError),
        ):
            PipelineConfig.from_env()

    def test_error_contains_key_and_value(self) -> None:
        """ConfigValidationError includes key and value attributes."""
        with (
            patch.dict(os.environ, {"IMAGERY_MAX_CLOUD_COVER_PCT": "200"}, clear=True),
            pytest.raises(ConfigValidationError) as exc_info,
        ):
            PipelineConfig.from_env()
        assert exc_info.value.key == "IMAGERY_MAX_CLOUD_COVER_PCT"
        assert exc_info.value.value == 200.0

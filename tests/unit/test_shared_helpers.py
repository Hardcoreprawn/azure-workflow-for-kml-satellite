"""Tests for shared constants and helper functions.

Verifies that centralised constants and helpers (Issue #52) behave
correctly and that activity modules re-export them for compatibility.

References:
    PID 7.4.5  (Explicit — named constants, no magic strings)
    PID 7.4.7  (Unit test tier)
    Issue #52  (Centralise shared pipeline constants and helpers)
"""

from __future__ import annotations

import unittest
from datetime import datetime

from kml_satellite.core.constants import INPUT_CONTAINER, OUTPUT_CONTAINER
from kml_satellite.utils.helpers import build_provider_config, parse_timestamp

# ---------------------------------------------------------------------------
# Tests — core.constants
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Verify centralised pipeline constants."""

    def test_output_container_value(self) -> None:
        assert OUTPUT_CONTAINER == "kml-output"

    def test_input_container_value(self) -> None:
        assert INPUT_CONTAINER == "kml-input"


# ---------------------------------------------------------------------------
# Tests — utils.helpers.build_provider_config
# ---------------------------------------------------------------------------


class TestBuildProviderConfig(unittest.TestCase):
    """build_provider_config helper."""

    def test_none_overrides_returns_minimal_config(self) -> None:
        config = build_provider_config("planetary_computer", None)
        assert config.name == "planetary_computer"
        assert config.api_base_url == ""

    def test_overrides_populate_fields(self) -> None:
        config = build_provider_config(
            "skywatch",
            {
                "api_base_url": "https://api.example.com",
                "auth_mechanism": "api_key",
                "keyvault_secret_name": "my-secret",  # pragma: allowlist secret
                "extra_params": {"output_container": "custom"},
            },
        )
        assert config.name == "skywatch"
        assert config.api_base_url == "https://api.example.com"
        assert config.auth_mechanism == "api_key"
        assert config.keyvault_secret_name == "my-secret"  # pragma: allowlist secret
        assert config.extra_params == {"output_container": "custom"}

    def test_empty_overrides_dict_returns_defaults(self) -> None:
        config = build_provider_config("test", {})
        assert config.name == "test"
        assert config.api_base_url == ""
        assert config.auth_mechanism == "none"


# ---------------------------------------------------------------------------
# Tests — utils.helpers.parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp(unittest.TestCase):
    """parse_timestamp helper."""

    def test_valid_iso_timestamp(self) -> None:
        result = parse_timestamp("2026-03-15T12:00:00+00:00")
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 15
        assert result.tzinfo is not None

    def test_empty_string_returns_now(self) -> None:
        before = datetime.now().astimezone()
        result = parse_timestamp("")
        after = datetime.now().astimezone()
        assert before <= result <= after

    def test_invalid_string_returns_now(self) -> None:
        before = datetime.now().astimezone()
        result = parse_timestamp("not-a-timestamp")
        after = datetime.now().astimezone()
        assert before <= result <= after

    def test_naive_iso_timestamp(self) -> None:
        result = parse_timestamp("2026-01-01T00:00:00")
        assert result.year == 2026


# ---------------------------------------------------------------------------
# Tests — backward compatibility re-exports
# ---------------------------------------------------------------------------


class TestBackwardCompatibility(unittest.TestCase):
    """Verify activity modules re-export shared helpers."""

    def test_download_imagery_exports_build_provider_config(self) -> None:
        from kml_satellite.activities.download_imagery import _build_provider_config

        assert _build_provider_config is build_provider_config

    def test_download_imagery_exports_parse_timestamp(self) -> None:
        from kml_satellite.activities.download_imagery import _parse_timestamp

        assert _parse_timestamp is parse_timestamp

    def test_acquire_imagery_exports_build_provider_config(self) -> None:
        from kml_satellite.activities.acquire_imagery import _build_provider_config

        assert _build_provider_config is build_provider_config

    def test_download_imagery_uses_central_output_container(self) -> None:
        from kml_satellite.activities.download_imagery import (
            OUTPUT_CONTAINER as DL_CONTAINER,
        )

        assert DL_CONTAINER == OUTPUT_CONTAINER

    def test_write_metadata_uses_central_output_container(self) -> None:
        from kml_satellite.activities.write_metadata import (
            OUTPUT_CONTAINER as WM_CONTAINER,
        )

        assert WM_CONTAINER == OUTPUT_CONTAINER

    def test_post_process_uses_central_output_container(self) -> None:
        from kml_satellite.activities.post_process_imagery import (
            OUTPUT_CONTAINER as PP_CONTAINER,
        )

        assert PP_CONTAINER == OUTPUT_CONTAINER

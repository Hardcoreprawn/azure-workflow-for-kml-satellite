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
from datetime import UTC, datetime

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

    def test_extra_params_none_returns_empty_dict(self) -> None:
        config = build_provider_config("test", {"extra_params": None})
        assert config.extra_params == {}

    def test_extra_params_non_dict_returns_empty_dict(self) -> None:
        config = build_provider_config("test", {"extra_params": "not-a-dict"})
        assert config.extra_params == {}


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
        before = datetime.now(UTC)
        result = parse_timestamp("")
        after = datetime.now(UTC)
        assert before <= result <= after

    def test_invalid_string_returns_now(self) -> None:
        before = datetime.now(UTC)
        result = parse_timestamp("not-a-timestamp")
        after = datetime.now(UTC)
        assert before <= result <= after

    def test_naive_iso_timestamp(self) -> None:
        result = parse_timestamp("2026-01-01T00:00:00")
        assert result.year == 2026
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_non_utc_offset_normalized(self) -> None:
        """Non-UTC offset should be converted to UTC."""
        result = parse_timestamp("2026-06-15T10:00:00+05:00")
        assert result.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
        assert result.hour == 5  # 10:00 +05:00 → 05:00 UTC

    def test_fallback_is_utc(self) -> None:
        """Empty input must produce a UTC-aware datetime, not local tz."""
        result = parse_timestamp("")
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_invalid_fallback_is_utc(self) -> None:
        """Unparseable input must produce a UTC-aware datetime."""
        result = parse_timestamp("garbage")
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Tests — backward compatibility re-exports
# ---------------------------------------------------------------------------


class TestBackwardCompatibility(unittest.TestCase):
    """Verify activity modules re-export shared helpers."""

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

"""Tests for configuration loading and validation (§8)."""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

from treesight.config import config_get_int
from treesight.errors import ConfigValidationError


class TestConfigGetInt:
    def test_int_value(self):
        assert config_get_int({"x": 42}, "x", 0) == 42

    def test_string_value(self):
        assert config_get_int({"x": "10"}, "x", 0) == 10

    def test_float_string_raises(self):
        with pytest.raises(ValueError):
            config_get_int({"x": "3.9"}, "x", 0)

    def test_missing_key_returns_default(self):
        assert config_get_int({}, "x", 99) == 99

    def test_none_value_returns_default(self):
        assert config_get_int({"x": None}, "x", 7) == 7

    def test_garbage_string_raises(self):
        with pytest.raises(ValueError):
            config_get_int({"x": "not-a-number"}, "x", 5)

    def test_float_value_non_integer_raises(self):
        with pytest.raises(ValueError):
            config_get_int({"x": 3.7}, "x", 0)

    def test_float_value_integer_ok(self):
        assert config_get_int({"x": 4.0}, "x", 0) == 4


class TestValidateConfig:
    def test_valid_bearer_defaults_pass(self):
        """Bearer-only mode should pass when required CIAM settings are present."""
        with patch.dict(
            os.environ,
            {
                "AUTH_MODE": "bearer_only",
                "CIAM_AUTHORITY": "https://issuer.example",
                "CIAM_TENANT_ID": "tenant-id",
                "CIAM_API_AUDIENCE": "client-id",
            },
            clear=False,
        ):
            cfg = importlib.import_module("treesight.config")
            importlib.reload(cfg)
            cfg.validate_config()
            importlib.reload(cfg)

    def test_invalid_resolution_raises(self):
        with patch.dict(os.environ, {"IMAGERY_RESOLUTION_TARGET_M": "0"}):
            # Need to reimport to pick up env change
            cfg = importlib.import_module("treesight.config")
            importlib.reload(cfg)
            with pytest.raises(ConfigValidationError):
                cfg.validate_config()
            # Reset
            importlib.reload(cfg)

    def test_invalid_cloud_cover_raises(self):
        with patch.dict(os.environ, {"IMAGERY_MAX_CLOUD_COVER_PCT": "150"}):
            cfg = importlib.import_module("treesight.config")
            importlib.reload(cfg)
            with pytest.raises(ConfigValidationError):
                cfg.validate_config()
            importlib.reload(cfg)

    def test_bearer_only_requires_ciam_settings(self):
        with patch.dict(
            os.environ,
            {
                "AUTH_MODE": "bearer_only",
                "CIAM_AUTHORITY": "",
                "CIAM_TENANT_ID": "",
                "CIAM_API_AUDIENCE": "",
            },
            clear=False,
        ):
            cfg = importlib.import_module("treesight.config")
            importlib.reload(cfg)
            with pytest.raises(ConfigValidationError, match="CIAM_AUTHORITY"):
                cfg.validate_config()
            importlib.reload(cfg)

    def test_bearer_only_with_valid_settings_passes(self):
        with patch.dict(
            os.environ,
            {
                "AUTH_MODE": "bearer_only",
                "CIAM_AUTHORITY": "https://issuer.example",
                "CIAM_TENANT_ID": "tenant-id",
                "CIAM_API_AUDIENCE": "client-id",
                "CIAM_JWT_LEEWAY_SECONDS": "60",
            },
            clear=False,
        ):
            cfg = importlib.import_module("treesight.config")
            importlib.reload(cfg)
            cfg.validate_config()
            importlib.reload(cfg)

    def test_rejects_invalid_auth_mode(self):
        with patch.dict(os.environ, {"AUTH_MODE": "unsupported-mode"}, clear=False):
            cfg = importlib.import_module("treesight.config")
            importlib.reload(cfg)
            with pytest.raises(ConfigValidationError, match="AUTH_MODE"):
                cfg.validate_config()
            importlib.reload(cfg)

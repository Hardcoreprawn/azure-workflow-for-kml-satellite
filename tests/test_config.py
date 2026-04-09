"""Tests for configuration loading and validation (§8)."""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

import pytest

from treesight.config import config_get_int, validate_config
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
    def test_valid_defaults_pass(self):
        """Default env should pass validation (no errors)."""
        validate_config()  # Should not raise

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

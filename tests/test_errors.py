"""Tests for exception hierarchy (§9)."""

from __future__ import annotations

from treesight.errors import (
    ConfigValidationError,
    ContractError,
    ModelValidationError,
    PipelineError,
    ProviderAuthError,
    ProviderDownloadError,
    ProviderError,
    ProviderOrderError,
    ProviderSearchError,
)


class TestExceptionHierarchy:
    def test_pipeline_error_is_base(self):
        assert issubclass(ContractError, PipelineError)
        assert issubclass(ConfigValidationError, PipelineError)
        assert issubclass(ModelValidationError, PipelineError)
        assert issubclass(ProviderError, PipelineError)

    def test_provider_errors_inherit(self):
        assert issubclass(ProviderAuthError, ProviderError)
        assert issubclass(ProviderSearchError, ProviderError)
        assert issubclass(ProviderOrderError, ProviderError)
        assert issubclass(ProviderDownloadError, ProviderError)

    def test_contract_error_stage(self):
        e = ContractError("bad input")
        assert e.stage == "ingress"
        assert e.retryable is False

    def test_config_error_stage(self):
        e = ConfigValidationError("bad config")
        assert e.stage == "config"
        assert e.code == "CONFIG_INVALID"

    def test_provider_error_retryable(self):
        e = ProviderSearchError("timeout", retryable=True)
        assert e.retryable is True
        assert e.stage == "provider"

    def test_provider_auth_not_retryable(self):
        e = ProviderAuthError("401")
        assert e.retryable is False

    def test_pipeline_error_message(self):
        e = PipelineError("something broke", stage="test", code="TEST_ERR")
        assert str(e) == "something broke"
        assert e.stage == "test"
        assert e.code == "TEST_ERR"

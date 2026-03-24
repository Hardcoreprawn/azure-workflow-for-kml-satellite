"""Exception hierarchy (§9 of SYSTEM_SPEC)."""

from __future__ import annotations


class PipelineError(Exception):
    """Base exception for all pipeline errors."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "",
        code: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.retryable = retryable


class ContractError(PipelineError):
    """Payload / input validation failure."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message, stage="ingress", code=code, retryable=False)


class ConfigValidationError(PipelineError):
    """Invalid configuration at startup."""

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="config", code="CONFIG_INVALID", retryable=False)


class ModelValidationError(PipelineError):
    """Domain model invariant violation."""

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="model", code="MODEL_INVALID", retryable=False)


# --- Provider errors ---


class ProviderError(PipelineError):
    """Base for all imagery provider failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, stage="provider", retryable=retryable)


class ProviderAuthError(ProviderError):
    """Authentication failure (non-retryable)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ProviderSearchError(ProviderError):
    """Search request failed."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)


class ProviderOrderError(ProviderError):
    """Order submission failed."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)


class ProviderDownloadError(ProviderError):
    """Download failed."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)


# --- Billing errors ---


class BillingError(PipelineError):
    """Billing / subscription failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, stage="billing", code="BILLING_ERROR", retryable=False)

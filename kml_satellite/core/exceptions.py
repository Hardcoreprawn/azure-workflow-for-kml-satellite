"""Unified activity exception taxonomy.

Provides a shared base exception hierarchy for all pipeline activities
and providers. Every domain exception inherits from ``PipelineError``
and carries structured context fields that enable consistent retry
decisions, alerting, and operator diagnostics.

Taxonomy categories
-------------------
- ``ValidationError``   — input/contract violations, never retryable.
- ``TransientError``    — temporary failures (network, throttle), retryable.
- ``PermanentError``    — unrecoverable domain failures, not retryable.
- ``ContractError``     — payload/schema drift between stages, never retryable.

Every exception exposes ``to_error_dict()`` for a stable structured
error payload suitable for orchestrator history and logging.

References:
    PID 7.4.2  (Fail Loudly, Fail Safely)
    PID 7.4.5  (Explicit Over Implicit)
    Issue #58
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base exception for all pipeline-domain errors.

    Attributes:
        message: Human-readable error description.
        stage: Pipeline stage where the error occurred
            (e.g. ``"parse_kml"``, ``"download_imagery"``).
        code: Machine-readable error code (e.g. ``"KML_PARSE_FAILED"``).
        retryable: Whether the orchestrator should retry the operation.
        correlation_id: Request/orchestration correlation identifier.
    """

    #: Default stage for subclasses (override via class attribute or kwarg).
    default_stage: str = ""
    #: Default code for subclasses (override via class attribute or kwarg).
    default_code: str = ""

    def __init__(
        self,
        message: str = "",
        *,
        stage: str = "",
        code: str = "",
        retryable: bool = False,
        correlation_id: str = "",
    ) -> None:
        self.message = message
        self.stage = stage or self.default_stage
        self.code = code or self.default_code
        self.retryable = retryable
        self.correlation_id = correlation_id
        super().__init__(message)

    @property
    def category(self) -> str:
        """Return the error category based on concrete class."""
        if isinstance(self, ContractError):
            return "contract"
        if isinstance(self, ValidationError):
            return "validation"
        if isinstance(self, TransientError):
            return "transient"
        if isinstance(self, PermanentError):
            return "permanent"
        return "transient" if self.retryable else "permanent"

    def to_error_dict(self) -> dict[str, object]:
        """Return a structured error payload with stable keys.

        Suitable for orchestrator history, logging, and alerting.
        """
        return {
            "category": self.category,
            "code": self.code,
            "stage": self.stage,
            "message": self.message,
            "retryable": self.retryable,
            "correlation_id": self.correlation_id,
        }


# ---------------------------------------------------------------------------
# Category base classes
# ---------------------------------------------------------------------------


class ValidationError(PipelineError):
    """Input or domain-model validation failure. Never retryable."""

    def __init__(self, message: str = "", **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class TransientError(PipelineError):
    """Temporary failure that may succeed on retry."""

    def __init__(self, message: str = "", **kwargs: object) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class PermanentError(PipelineError):
    """Unrecoverable domain failure. Not retryable."""

    def __init__(self, message: str = "", **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class ContractError(PipelineError):
    """Payload or schema drift between pipeline stages. Never retryable."""

    def __init__(self, message: str = "", **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]

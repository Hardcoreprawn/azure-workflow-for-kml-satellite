"""Workflow state constants using StrEnum (Python 3.11+).

Centralizes state strings to prevent typos and enable exhaustive pattern matching.
All state comparisons should use these enum values instead of string literals.

References:
    PEP 663 -- Enum: StrEnum
    Python 3.11+ What's New
"""

from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    """Standard workflow states for imagery acquisition pipeline.

    StrEnum automatically converts to/from strings, so you can compare
    directly with string values in dicts without .value:

        if result.get("state") == WorkflowState.READY:  # Works!
    """

    # Success states
    READY = "ready"
    COMPLETED = "completed"
    SUCCESS = "success"

    # In-progress states
    PENDING = "pending"
    PROCESSING = "processing"

    # Terminal failure states
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"

    # Unknown/undefined
    UNKNOWN = "unknown"

    @classmethod
    def is_success(cls, state: str | WorkflowState) -> bool:
        """Check if state represents success/completion.

        Args:
            state: State string or enum value.

        Returns:
            True if state is ready/completed/success.
        """
        return state in {cls.READY, cls.COMPLETED, cls.SUCCESS}

    @classmethod
    def is_terminal(cls, state: str | WorkflowState) -> bool:
        """Check if state is terminal (no further processing).

        Args:
            state: State string or enum value.

        Returns:
            True if state is ready/failed/cancelled.
        """
        return state in {
            cls.READY,
            cls.COMPLETED,
            cls.SUCCESS,
            cls.FAILED,
            cls.ERROR,
            cls.CANCELLED,
        }

    @classmethod
    def is_failure(cls, state: str | WorkflowState) -> bool:
        """Check if state represents a failure.

        Args:
            state: State string or enum value.

        Returns:
            True if state is failed/error.
        """
        return state in {cls.FAILED, cls.ERROR}

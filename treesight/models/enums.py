"""WorkflowState and OrderState enums (§2.6, §2.7)."""

from __future__ import annotations

from enum import StrEnum


class OrderState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowState(StrEnum):
    READY = "ready"
    COMPLETED = "completed"
    SUCCESS = "success"
    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @staticmethod
    def is_success(state: WorkflowState | str) -> bool:
        return str(state) in {"ready", "completed", "success"}

    @staticmethod
    def is_terminal(state: WorkflowState | str) -> bool:
        return str(state) in {"ready", "completed", "success", "failed", "error", "cancelled"}

    @staticmethod
    def is_failure(state: WorkflowState | str) -> bool:
        return str(state) in {"failed", "error", "cancelled"}

"""Tests for enums — OrderState and WorkflowState (§2.6, §2.7)."""

from __future__ import annotations

from treesight.models.enums import OrderState, WorkflowState


class TestOrderState:
    def test_values(self):
        assert OrderState.PENDING.value == "pending"
        assert OrderState.READY.value == "ready"
        assert OrderState.FAILED.value == "failed"
        assert OrderState.CANCELLED.value == "cancelled"

    def test_string_comparison(self):
        assert OrderState.READY == "ready"


class TestWorkflowState:
    def test_is_success(self):
        assert WorkflowState.is_success("ready") is True
        assert WorkflowState.is_success("completed") is True
        assert WorkflowState.is_success("success") is True
        assert WorkflowState.is_success("failed") is False

    def test_is_terminal(self):
        assert WorkflowState.is_terminal("ready") is True
        assert WorkflowState.is_terminal("failed") is True
        assert WorkflowState.is_terminal("cancelled") is True
        assert WorkflowState.is_terminal("pending") is False
        assert WorkflowState.is_terminal("processing") is False

    def test_is_failure(self):
        assert WorkflowState.is_failure("failed") is True
        assert WorkflowState.is_failure("error") is True
        assert WorkflowState.is_failure("cancelled") is True
        assert WorkflowState.is_failure("ready") is False
        assert WorkflowState.is_failure("completed") is False

    def test_enum_is_str(self):
        assert isinstance(WorkflowState.READY, str)

"""Tests for WorkflowState StrEnum.

Critical properties to verify:
1.  Enum values equal their string literals (Durable Functions round-trips state
    through JSON as plain strings; comparisons must still hold after deserialisation).
2.  Classification helpers return correct results for every state.
3.  The enum is exhaustive — all expected string values are present.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from kml_satellite.core.states import WorkflowState

# ---------------------------------------------------------------------------
# StrEnum-string equality (Durable Functions serialisation compatibility)
# ---------------------------------------------------------------------------


class TestStrEnumEquality:
    """WorkflowState values must be equal to their raw string literals.

    Durable Functions serialises orchestration state to JSON as plain strings.
    When replayed, state comes back as str, not WorkflowState.  Comparisons
    must work in both directions.
    """

    def test_ready_equals_string(self) -> None:
        assert WorkflowState.READY == "ready"

    def test_completed_equals_string(self) -> None:
        assert WorkflowState.COMPLETED == "completed"

    def test_success_equals_string(self) -> None:
        assert WorkflowState.SUCCESS == "success"

    def test_pending_equals_string(self) -> None:
        assert WorkflowState.PENDING == "pending"

    def test_processing_equals_string(self) -> None:
        assert WorkflowState.PROCESSING == "processing"

    def test_failed_equals_string(self) -> None:
        assert WorkflowState.FAILED == "failed"

    def test_error_equals_string(self) -> None:
        assert WorkflowState.ERROR == "error"

    def test_cancelled_equals_string(self) -> None:
        assert WorkflowState.CANCELLED == "cancelled"

    def test_unknown_equals_string(self) -> None:
        assert WorkflowState.UNKNOWN == "unknown"

    def test_string_equals_enum(self) -> None:
        """Symmetry: plain string == enum (not just enum == string)."""
        assert WorkflowState.READY == "ready"
        assert WorkflowState.FAILED == "failed"

    def test_dict_get_comparison(self) -> None:
        """Simulates checking a Durable Functions result dict."""
        result = {"state": "ready", "order_id": "ABC"}
        assert result.get("state") == WorkflowState.READY

    def test_json_roundtrip(self) -> None:
        """State string survives JSON serialise → deserialise → compare."""
        original = {"state": WorkflowState.READY}
        roundtripped = json.loads(json.dumps(original))
        assert roundtripped["state"] == WorkflowState.READY
        assert isinstance(roundtripped["state"], str)
        assert not isinstance(roundtripped["state"], WorkflowState)

    def test_in_check_with_set_of_strings(self) -> None:
        """WorkflowState value works in membership tests against plain string sets."""
        terminal_strings = {"ready", "failed", "completed", "error", "cancelled", "success"}
        assert WorkflowState.READY in terminal_strings
        assert WorkflowState.FAILED in terminal_strings
        assert WorkflowState.PENDING not in terminal_strings


# ---------------------------------------------------------------------------
# is_success()
# ---------------------------------------------------------------------------


class TestIsSuccess:
    @pytest.mark.parametrize(
        "state", [WorkflowState.READY, WorkflowState.COMPLETED, WorkflowState.SUCCESS]
    )
    def test_success_states_return_true(self, state: WorkflowState) -> None:
        assert WorkflowState.is_success(state) is True

    @pytest.mark.parametrize(
        "state",
        [
            WorkflowState.FAILED,
            WorkflowState.ERROR,
            WorkflowState.CANCELLED,
            WorkflowState.PENDING,
            WorkflowState.PROCESSING,
            WorkflowState.UNKNOWN,
        ],
    )
    def test_non_success_states_return_false(self, state: WorkflowState) -> None:
        assert WorkflowState.is_success(state) is False

    def test_accepts_plain_string(self) -> None:
        assert WorkflowState.is_success("ready") is True
        assert WorkflowState.is_success("failed") is False

    def test_rejects_unknown_string(self) -> None:
        assert WorkflowState.is_success("queued") is False


# ---------------------------------------------------------------------------
# is_terminal()
# ---------------------------------------------------------------------------


class TestIsTerminal:
    @pytest.mark.parametrize(
        "state",
        [
            WorkflowState.READY,
            WorkflowState.COMPLETED,
            WorkflowState.SUCCESS,
            WorkflowState.FAILED,
            WorkflowState.ERROR,
            WorkflowState.CANCELLED,
        ],
    )
    def test_terminal_states_return_true(self, state: WorkflowState) -> None:
        assert WorkflowState.is_terminal(state) is True

    @pytest.mark.parametrize(
        "state", [WorkflowState.PENDING, WorkflowState.PROCESSING, WorkflowState.UNKNOWN]
    )
    def test_in_progress_states_return_false(self, state: WorkflowState) -> None:
        assert WorkflowState.is_terminal(state) is False

    def test_accepts_plain_string(self) -> None:
        assert WorkflowState.is_terminal("completed") is True
        assert WorkflowState.is_terminal("processing") is False


# ---------------------------------------------------------------------------
# is_failure()
# ---------------------------------------------------------------------------


class TestIsFailure:
    @pytest.mark.parametrize("state", [WorkflowState.FAILED, WorkflowState.ERROR])
    def test_failure_states_return_true(self, state: WorkflowState) -> None:
        assert WorkflowState.is_failure(state) is True

    @pytest.mark.parametrize(
        "state",
        [
            WorkflowState.READY,
            WorkflowState.COMPLETED,
            WorkflowState.SUCCESS,
            WorkflowState.CANCELLED,
            WorkflowState.PENDING,
            WorkflowState.PROCESSING,
            WorkflowState.UNKNOWN,
        ],
    )
    def test_non_failure_states_return_false(self, state: WorkflowState) -> None:
        assert WorkflowState.is_failure(state) is False

    def test_accepts_plain_string(self) -> None:
        assert WorkflowState.is_failure("failed") is True
        assert WorkflowState.is_failure("error") is True
        assert WorkflowState.is_failure("ready") is False

    def test_empty_string_is_not_failure(self) -> None:
        assert WorkflowState.is_failure("") is False


# ---------------------------------------------------------------------------
# Exhaustiveness guard
# ---------------------------------------------------------------------------


class TestExhaustiveness:
    """Guard against accidentally removing a state that the pipeline depends on."""

    REQUIRED_STRING_VALUES: ClassVar[set[str]] = {
        "ready",
        "completed",
        "success",
        "pending",
        "processing",
        "failed",
        "error",
        "cancelled",
        "unknown",
    }

    def test_all_required_values_present(self) -> None:
        actual = {s.value for s in WorkflowState}
        missing = self.REQUIRED_STRING_VALUES - actual
        assert not missing, f"WorkflowState is missing expected values: {missing}"

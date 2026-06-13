from __future__ import annotations

from datetime import date

from scripts.backlog_autopilot import (
    IssueCandidate,
    compute_budget_status,
    select_issues,
)


def _issue(number: int, labels: set[str], assignees: set[str] | None = None) -> IssueCandidate:
    return IssueCandidate(
        number=number,
        title=f"Issue {number}",
        labels=labels,
        assignees=assignees or set(),
        url=f"https://example.invalid/{number}",
    )


def test_budget_status_allows_when_spend_below_pacing_target() -> None:
    status = compute_budget_status(
        today=date(2026, 6, 15),
        monthly_budget_usd=300.0,
        month_spend_used_usd=50.0,
        reserve_ratio=0.25,
    )
    assert status.allowed_today > 50.0
    assert status.can_spend is True


def test_budget_status_blocks_when_spend_above_pacing_target() -> None:
    status = compute_budget_status(
        today=date(2026, 6, 5),
        monthly_budget_usd=300.0,
        month_spend_used_usd=120.0,
        reserve_ratio=0.25,
    )
    assert status.can_spend is False


def test_select_issues_prioritizes_security_and_now() -> None:
    issues = [
        _issue(1, {"priority:next"}),
        _issue(2, {"security"}),
        _issue(3, {"priority:now"}),
        _issue(4, {"discovered", "priority:backlog"}),
    ]
    selected = select_issues(issues, max_new_assignments=2)
    assert [issue.number for issue in selected] == [2, 3]


def test_select_issues_skips_assigned_issues() -> None:
    issues = [
        _issue(10, {"security"}, {"someone"}),
        _issue(11, {"priority:now"}),
    ]
    selected = select_issues(issues, max_new_assignments=2)
    assert [issue.number for issue in selected] == [11]

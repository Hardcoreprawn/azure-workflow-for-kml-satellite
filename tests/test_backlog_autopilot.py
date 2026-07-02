from __future__ import annotations

from datetime import date

from scripts.backlog_autopilot import (
    COPILOT_ACTOR_ID,
    IssueCandidate,
    assign_issue_to_copilot,
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


def test_select_issues_prefers_oldest_within_same_tier() -> None:
    # Within one priority tier, the oldest (lowest-numbered) issues go first so
    # agents drain the backlog bottom-up rather than grabbing the newest.
    issues = [
        _issue(300, {"discovered"}),
        _issue(100, {"discovered"}),
        _issue(200, {"discovered"}),
    ]
    selected = select_issues(issues, max_new_assignments=2)
    assert [issue.number for issue in selected] == [100, 200]


def test_select_issues_skips_assigned_issues() -> None:
    issues = [
        _issue(10, {"security"}, {"someone"}),
        _issue(11, {"priority:now"}),
    ]
    selected = select_issues(issues, max_new_assignments=2)
    assert [issue.number for issue in selected] == [11]


def test_assign_issue_to_copilot_adds_actor_id(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_graphql(*, token: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        calls.append((query, variables))
        if "query AssignableIssue" in query:
            return {
                "repository": {
                    "issue": {
                        "id": "I_123",
                        "assignees": {"nodes": [{"id": "U_1", "login": "Hardcoreprawn"}]},
                    }
                }
            }
        return {"replaceActorsForAssignable": {"__typename": "ReplaceActorsForAssignablePayload"}}

    monkeypatch.setattr("scripts.backlog_autopilot._github_graphql", fake_graphql)

    assign_issue_to_copilot(token="t", owner="o", repo="r", issue_number=850)

    assert len(calls) == 2
    mutation_variables = calls[1][1]
    assert mutation_variables["input"] == {
        "assignableId": "I_123",
        "actorIds": ["U_1", COPILOT_ACTOR_ID],
    }


def test_assign_issue_to_copilot_noop_when_already_assigned(monkeypatch) -> None:
    calls: list[str] = []

    def fake_graphql(*, token: str, query: str, variables: dict[str, object]) -> dict[str, object]:
        calls.append(query)
        return {
            "repository": {
                "issue": {
                    "id": "I_123",
                    "assignees": {"nodes": [{"id": COPILOT_ACTOR_ID, "login": "Copilot"}]},
                }
            }
        }

    monkeypatch.setattr("scripts.backlog_autopilot._github_graphql", fake_graphql)

    assign_issue_to_copilot(token="t", owner="o", repo="r", issue_number=850)

    assert len(calls) == 1

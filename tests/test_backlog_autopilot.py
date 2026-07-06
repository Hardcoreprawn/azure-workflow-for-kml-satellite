from __future__ import annotations

from datetime import date

from scripts.backlog_autopilot import (
    COPILOT_ACTOR_ID,
    IssueCandidate,
    assign_issue_to_copilot,
    compute_budget_status,
    count_open_copilot_prs,
    parse_args,
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


def test_select_issues_assigns_must_before_should_and_excludes_others() -> None:
    # Auto-assignment is MoSCoW-driven: Must ranks above Should, and
    # Could/Won't/untagged/epic are never auto-assigned.
    issues = [
        _issue(1, {"moscow:should"}),
        _issue(2, {"moscow:could"}),  # not auto-eligible
        _issue(3, {"moscow:must"}),
        _issue(4, {"moscow:wont"}),  # not auto-eligible
        _issue(5, {"epic", "moscow:must"}),  # epics are trackers, excluded
        _issue(6, set()),  # untagged, excluded
    ]
    selected = select_issues(issues, max_new_assignments=5)
    assert [issue.number for issue in selected] == [3, 1]


def test_select_issues_excludes_no_autopilot_label() -> None:
    # `no-autopilot` gates approval-gated / human-design work out of the fleet.
    issues = [
        _issue(1, {"moscow:must", "no-autopilot"}),
        _issue(2, {"moscow:should"}),
    ]
    selected = select_issues(issues, max_new_assignments=5)
    assert [issue.number for issue in selected] == [2]


def test_select_issues_security_floats_to_top_within_tier() -> None:
    # Security floor: within a MoSCoW tier the top security item is never starved.
    issues = [
        _issue(10, {"moscow:must"}),
        _issue(11, {"moscow:must", "security"}),
    ]
    selected = select_issues(issues, max_new_assignments=1)
    assert [issue.number for issue in selected] == [11]


def test_select_issues_prefers_oldest_within_same_tier() -> None:
    # Within one MoSCoW tier, the oldest (lowest-numbered) issues go first so
    # agents drain the backlog bottom-up rather than grabbing the newest.
    issues = [
        _issue(300, {"moscow:should"}),
        _issue(100, {"moscow:should"}),
        _issue(200, {"moscow:should"}),
    ]
    selected = select_issues(issues, max_new_assignments=2)
    assert [issue.number for issue in selected] == [100, 200]


def test_select_issues_skips_assigned_issues() -> None:
    issues = [
        _issue(10, {"moscow:must"}, {"someone"}),
        _issue(11, {"moscow:should"}),
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


def test_max_open_autopilot_prs_default_enforces_wip_limit(monkeypatch) -> None:
    # WIP limit contract: the autopilot must not start new agent work beyond
    # 3 concurrent open Copilot PRs. This default is the enforced ceiling when
    # the AUTOPILOT_MAX_OPEN_AUTOPILOT_PRS repo variable is unset.
    monkeypatch.setattr(
        "sys.argv",
        [
            "backlog_autopilot",
            "--owner",
            "o",
            "--repo",
            "r",
            "--monthly-budget-usd",
            "200",
            "--month-spend-used-usd",
            "0",
        ],
    )
    args = parse_args()
    assert args.max_open_autopilot_prs == 3


def test_count_open_copilot_prs_counts_drafts_and_ready_agent_prs(monkeypatch) -> None:
    # WIP scope: the limit counts all open Copilot-authored PRs regardless of
    # draft state, plus any [WIP]-titled PR. Non-agent PRs do not count.
    open_prs = [
        {"user": {"login": "Copilot"}, "draft": True, "title": "fix: something"},
        {"user": {"login": "Copilot"}, "draft": False, "title": "feat: ready"},
        {"user": {"login": "Hardcoreprawn"}, "draft": False, "title": "[WIP] manual"},
        {"user": {"login": "Hardcoreprawn"}, "draft": False, "title": "docs: normal"},
        {"user": {"login": "dependabot[bot]"}, "draft": False, "title": "deps: bump"},
    ]
    monkeypatch.setattr(
        "scripts.backlog_autopilot._fetch_paginated",
        lambda token, path: open_prs,
    )

    count = count_open_copilot_prs(token="t", owner="o", repo="r")

    # 2 Copilot PRs (draft + ready) + 1 [WIP]-titled PR = 3; the two other
    # human/bot PRs are excluded.
    assert count == 3

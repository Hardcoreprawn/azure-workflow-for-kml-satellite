from __future__ import annotations

from datetime import date

from scripts.backlog_autopilot import (
    COPILOT_ACTOR_ID,
    IssueCandidate,
    assign_issue_to_copilot,
    compute_budget_status,
    count_open_copilot_prs,
    fallback_priority_score,
    parse_args,
    parse_blocking_refs,
    parse_closing_refs,
    select_issues,
)


def _issue(
    number: int,
    labels: set[str],
    assignees: set[str] | None = None,
    body: str = "",
) -> IssueCandidate:
    return IssueCandidate(
        number=number,
        title=f"Issue {number}",
        labels=labels,
        assignees=assignees or set(),
        url=f"https://example.invalid/{number}",
        body=body,
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


def test_parse_blocking_refs_reads_blocked_by_and_depends_on() -> None:
    body = "Foo.\nBlocked by #686.\nAlso depends on #700.\nsee #5 for context."
    assert parse_blocking_refs(body) == {686, 700}


def test_parse_blocking_refs_empty_when_no_dependency() -> None:
    assert parse_blocking_refs("Just a plain issue mentioning #5.") == set()


def test_select_issues_skips_issue_blocked_by_open_issue() -> None:
    # #10 depends on #9, and #9 is still open in this snapshot -> hold #10 back.
    issues = [
        _issue(9, {"moscow:must"}),
        _issue(10, {"moscow:must"}, body="Depends on #9."),
    ]
    selected = select_issues(issues, max_new_assignments=5)
    assert [issue.number for issue in selected] == [9]


def test_select_issues_assigns_when_blocker_is_closed() -> None:
    # #9 is absent from the snapshot (closed) -> #10's dependency is met.
    issues = [_issue(10, {"moscow:must"}, body="Blocked by #9.")]
    selected = select_issues(issues, max_new_assignments=5)
    assert [issue.number for issue in selected] == [10]


def test_select_issues_excludes_blocked_label() -> None:
    # `blocked` gates an issue whose prerequisite is not yet done.
    issues = [
        _issue(1, {"moscow:must", "blocked"}),
        _issue(2, {"moscow:should"}),
    ]
    selected = select_issues(issues, max_new_assignments=5)
    assert [issue.number for issue in selected] == [2]


def test_parse_closing_refs_reads_closing_keywords() -> None:
    body = "Work.\nCloses #1055\nfixes #7\nresolved #9\nsee #3 for context."
    assert parse_closing_refs(body) == {1055, 7, 9}


def test_select_issues_skips_issue_with_open_linked_pr() -> None:
    # #5 already has an open PR (Closes #5) -> do not re-dispatch it; #6 is free.
    issues = [_issue(5, {"moscow:must"}), _issue(6, {"moscow:must"})]
    selected = select_issues(issues, max_new_assignments=5, issues_with_open_prs={5})
    assert [issue.number for issue in selected] == [6]


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


def test_select_issues_falls_back_to_could_when_no_must_or_should() -> None:
    # Idle fallback: when nothing in the Must/Should tier is dispatchable, the
    # autopilot relaxes to the next most valuable tier (Could) rather than idle.
    issues = [
        _issue(1, {"moscow:could"}),
        _issue(2, {"moscow:could"}),
    ]
    selected = select_issues(issues, max_new_assignments=1)
    # Oldest Could first, consistent with primary-tier ordering.
    assert [issue.number for issue in selected] == [1]


def test_select_issues_does_not_use_fallback_when_primary_available() -> None:
    # Could work must never be picked while Must/Should work is dispatchable.
    issues = [
        _issue(1, {"moscow:could"}),
        _issue(2, {"moscow:should"}),
    ]
    selected = select_issues(issues, max_new_assignments=5)
    assert [issue.number for issue in selected] == [2]


def test_select_issues_fallback_disabled_returns_empty() -> None:
    # With the fallback gate off, an all-Could backlog yields nothing.
    issues = [_issue(1, {"moscow:could"})]
    selected = select_issues(issues, max_new_assignments=5, allow_idle_fallback=False)
    assert selected == []


def test_select_issues_fallback_still_excludes_wont_untagged_and_gated() -> None:
    # The fallback tier relaxes exactly one rung (Could). Won't, untagged, and
    # excluded-label work stay ineligible even when nothing else is available.
    issues = [
        _issue(1, {"moscow:wont"}),
        _issue(2, set()),  # untagged
        _issue(3, {"moscow:could", "no-autopilot"}),
        _issue(4, {"moscow:could", "epic"}),
        _issue(5, {"moscow:could", "blocked"}),
    ]
    selected = select_issues(issues, max_new_assignments=5)
    assert selected == []


def test_select_issues_fallback_respects_assignment_and_dependency_blocks() -> None:
    # Fallback Could work is still skipped when assigned or blocked by an open
    # issue, exactly like the primary tier.
    issues = [
        _issue(10, {"moscow:could"}, {"someone"}),
        _issue(11, {"moscow:could"}, body="Blocked by #12."),
        _issue(12, {"moscow:could"}),
    ]
    selected = select_issues(issues, max_new_assignments=5)
    # #10 assigned, #11 blocked by open #12 -> only #12 is dispatchable.
    assert [issue.number for issue in selected] == [12]


def test_fallback_priority_score_ranks_could_and_gates_others() -> None:
    assert fallback_priority_score({"moscow:could"}) > 0
    # Security and priority hints refine ordering within the Could tier.
    assert fallback_priority_score({"moscow:could", "security"}) > fallback_priority_score(
        {"moscow:could"}
    )
    assert fallback_priority_score({"moscow:could", "priority:now"}) > fallback_priority_score(
        {"moscow:could"}
    )
    # Non-Could and gated labels score 0.
    assert fallback_priority_score({"moscow:should"}) == 0
    assert fallback_priority_score({"moscow:wont"}) == 0
    assert fallback_priority_score(set()) == 0
    assert fallback_priority_score({"moscow:could", "no-autopilot"}) == 0


def test_no_idle_fallback_flag_defaults_to_enabled() -> None:
    # The idle fallback is on by default; --no-idle-fallback opts out.
    argv = [
        "backlog_autopilot",
        "--owner",
        "o",
        "--repo",
        "r",
        "--monthly-budget-usd",
        "200",
        "--month-spend-used-usd",
        "0",
    ]
    import sys

    original = sys.argv
    try:
        sys.argv = argv
        assert parse_args().no_idle_fallback is False
        sys.argv = [*argv, "--no-idle-fallback"]
        assert parse_args().no_idle_fallback is True
    finally:
        sys.argv = original


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

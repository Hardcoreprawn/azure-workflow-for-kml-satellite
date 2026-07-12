from __future__ import annotations

from scripts.code_scanning_issues import (
    CodeScanningAlert,
    TrackedIssue,
    build_issue_spec,
    plan_sync,
)


def _alert(number: int, severity: str = "high") -> CodeScanningAlert:
    return CodeScanningAlert(
        number=number,
        html_url=f"https://github.com/example/repo/security/code-scanning/{number}",
        rule_id="TEST-RULE",
        rule_description="Rule description",
        tool_name="Semgrep",
        severity=severity,
    )


def _tracked_issue(*, number: int, state: str, marker: int | None) -> TrackedIssue:
    body = "tracked"
    if marker is not None:
        body = f"tracked\n<!-- code-scanning-alert:{marker} -->"
    return TrackedIssue(
        number=number,
        state=state,
        title="Tracked",
        body=body,
        labels=("code-scanning-alert",),
    )


def test_build_issue_spec_embeds_marker_and_metadata() -> None:
    spec = build_issue_spec(alert=_alert(42, severity="critical"), label="code-scanning-alert")
    assert spec.alert_number == 42
    assert "<!-- code-scanning-alert:42 -->" in spec.body
    assert "Severity: `critical`" in spec.body
    assert "Semgrep" in spec.title


def test_plan_sync_creates_issue_when_alert_has_no_tracking_issue() -> None:
    plan = plan_sync(open_alerts=(_alert(12),), tracked_issues=(), label="code-scanning-alert")
    assert [item.alert_number for item in plan.create] == [12]
    assert plan.reopen == ()
    assert plan.close == ()


def test_plan_sync_is_idempotent_when_open_tracking_issue_exists() -> None:
    tracked = (_tracked_issue(number=2001, state="open", marker=12),)
    plan = plan_sync(open_alerts=(_alert(12),), tracked_issues=tracked, label="code-scanning-alert")
    assert plan.create == ()
    assert plan.reopen == ()
    assert plan.close == ()


def test_plan_sync_closes_tracking_issue_when_alert_no_longer_open() -> None:
    tracked = (_tracked_issue(number=3001, state="open", marker=88),)
    plan = plan_sync(open_alerts=(), tracked_issues=tracked, label="code-scanning-alert")
    assert plan.close == (3001,)
    assert plan.create == ()
    assert plan.reopen == ()


def test_plan_sync_reopens_closed_issue_for_reopened_alert() -> None:
    tracked = (_tracked_issue(number=4001, state="closed", marker=55),)
    plan = plan_sync(open_alerts=(_alert(55),), tracked_issues=tracked, label="code-scanning-alert")
    assert plan.create == ()
    assert len(plan.reopen) == 1
    assert plan.reopen[0][0] == 4001
    assert plan.reopen[0][1].alert_number == 55


def test_plan_sync_ignores_issues_without_marker() -> None:
    tracked = (_tracked_issue(number=5001, state="open", marker=None),)
    plan = plan_sync(open_alerts=(_alert(7),), tracked_issues=tracked, label="code-scanning-alert")
    assert [item.alert_number for item in plan.create] == [7]
    assert plan.close == ()

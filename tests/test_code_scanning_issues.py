from __future__ import annotations

from scripts.code_scanning_issues import (
    MARKER_PREFIX,
    CodeScanningAlert,
    TrackedIssue,
    build_issue_spec,
    filter_alerts_by_severity,
    parse_alert_marker,
    plan_sync,
)


def _alert(
    number: int,
    *,
    tool: str = "Trivy",
    rule_id: str = "CVE-2024-0001",
    severity: str = "high",
    description: str = "Example vulnerability",
) -> CodeScanningAlert:
    return CodeScanningAlert(
        number=number,
        state="open",
        tool=tool,
        rule_id=rule_id,
        rule_name=rule_id,
        description=description,
        severity=severity,
        html_url=f"https://example.invalid/alerts/{number}",
        location="path/to/file:1",
    )


def _tracked(alert_number: int, *, issue_number: int, state: str = "open") -> TrackedIssue:
    return TrackedIssue(number=issue_number, state=state, alert_number=alert_number)


def test_parse_alert_marker_reads_embedded_number() -> None:
    body = f"Some text\n<!-- {MARKER_PREFIX}2946 -->\nmore text"
    assert parse_alert_marker(body) == 2946


def test_parse_alert_marker_returns_none_when_absent() -> None:
    assert parse_alert_marker("no marker here") is None


def test_build_issue_spec_embeds_marker_and_metadata() -> None:
    alert = _alert(2946, rule_id="CVE-2026-1234", description="MessagePack recursion")
    spec = build_issue_spec(alert, labels=["security", "code-scanning"])

    assert f"<!-- {MARKER_PREFIX}2946 -->" in spec.body
    assert "CVE-2026-1234" in spec.body
    assert "Trivy" in spec.body
    assert alert.html_url in spec.body
    assert "code-scanning" in spec.labels
    # Alert number is in the title for human readability and stable identity.
    assert "2946" in spec.title


def test_plan_sync_creates_issues_for_untracked_open_alerts() -> None:
    alerts = [_alert(1), _alert(2)]
    tracked = [_tracked(1, issue_number=100)]

    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    assert [a.number for a in plan.to_create] == [2]
    assert plan.to_close == []


def test_plan_sync_closes_issues_whose_alert_is_resolved() -> None:
    # Alert 1 is still open; alert 2 no longer appears in open alerts.
    alerts = [_alert(1)]
    tracked = [
        _tracked(1, issue_number=100),
        _tracked(2, issue_number=101),
    ]

    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    assert plan.to_create == []
    assert [t.number for t in plan.to_close] == [101]


def test_plan_sync_ignores_already_closed_tracked_issues() -> None:
    # A closed tracking issue for a resolved alert must not be re-closed,
    # and a closed tracking issue for a still-open alert must be re-created.
    alerts = [_alert(1)]
    tracked = [_tracked(1, issue_number=100, state="closed")]

    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    assert [a.number for a in plan.to_create] == [1]
    assert plan.to_close == []


def test_filter_alerts_by_severity_keeps_all_when_no_filter() -> None:
    alerts = [_alert(1, severity="low"), _alert(2, severity="high")]
    assert filter_alerts_by_severity(alerts, allowed=frozenset()) == alerts


def test_filter_alerts_by_severity_is_case_insensitive() -> None:
    alerts = [_alert(1, severity="LOW"), _alert(2, severity="High")]
    kept = filter_alerts_by_severity(alerts, allowed=frozenset({"high", "critical"}))
    assert [a.number for a in kept] == [2]

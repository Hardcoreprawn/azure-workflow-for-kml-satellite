from __future__ import annotations

from scripts.code_scanning_issues import (
    GROUP_MARKER_PREFIX,
    MARKER_PREFIX,
    AlertGroup,
    CodeScanningAlert,
    TrackedIssue,
    build_group_issue_spec,
    build_issue_spec,
    filter_alerts_by_severity,
    group_alerts,
    parse_alert_marker,
    parse_all_alert_markers,
    parse_group_marker,
    plan_sync,
)


def _alert(
    number: int,
    *,
    tool: str = "Trivy",
    rule_id: str = "CVE-2024-0001",
    severity: str = "high",
    description: str = "Example vulnerability",
    location: str = "path/to/file:1",
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
        location=location,
    )


def _tracked(
    alert_number: int,
    *,
    issue_number: int,
    state: str = "open",
    group_key: tuple[str, str] | None = None,
    alert_numbers: frozenset[int] | None = None,
) -> TrackedIssue:
    return TrackedIssue(
        number=issue_number,
        state=state,
        alert_number=alert_number,
        group_key=group_key,
        alert_numbers=alert_numbers if alert_numbers is not None else frozenset(),
    )


# ── Marker parsing ─────────────────────────────────────────────


def test_parse_alert_marker_reads_embedded_number() -> None:
    body = f"Some text\n<!-- {MARKER_PREFIX}2946 -->\nmore text"
    assert parse_alert_marker(body) == 2946


def test_parse_alert_marker_returns_none_when_absent() -> None:
    assert parse_alert_marker("no marker here") is None


def test_parse_all_alert_markers_reads_single() -> None:
    body = f"<!-- {MARKER_PREFIX}42 -->\nsome text"
    assert parse_all_alert_markers(body) == frozenset({42})


def test_parse_all_alert_markers_reads_multiple() -> None:
    body = f"<!-- {MARKER_PREFIX}1 -->\n<!-- {MARKER_PREFIX}2 -->\n<!-- {MARKER_PREFIX}3 -->\n"
    assert parse_all_alert_markers(body) == frozenset({1, 2, 3})


def test_parse_all_alert_markers_returns_empty_frozenset_when_absent() -> None:
    assert parse_all_alert_markers("no markers") == frozenset()


def test_parse_group_marker_reads_embedded_key() -> None:
    body = f"<!-- {GROUP_MARKER_PREFIX}Trivy/CVE-2024-0001 -->"
    assert parse_group_marker(body) == ("Trivy", "CVE-2024-0001")


def test_parse_group_marker_preserves_slash_in_rule_id() -> None:
    # Semgrep rule IDs contain slashes; only the first slash is the separator.
    body = f"<!-- {GROUP_MARKER_PREFIX}Semgrep/python.lang.security.audit.xss -->"
    assert parse_group_marker(body) == ("Semgrep", "python.lang.security.audit.xss")


def test_parse_group_marker_returns_none_when_absent() -> None:
    assert parse_group_marker("no group marker here") is None


def test_parse_group_marker_returns_none_for_malformed_no_slash() -> None:
    body = f"<!-- {GROUP_MARKER_PREFIX}NoSlashHere -->"
    assert parse_group_marker(body) is None


# ── build_issue_spec (backward compat) ────────────────────────


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


# ── build_group_issue_spec ────────────────────────────────────


def test_build_group_issue_spec_embeds_group_marker() -> None:
    alert = _alert(1, rule_id="CVE-2024-9999")
    grp = AlertGroup(
        tool="Trivy",
        rule_id="CVE-2024-9999",
        rule_name="CVE-2024-9999",
        description="Test CVE",
        severity="high",
        alerts=(alert,),
    )
    spec = build_group_issue_spec(grp, labels=["security", "code-scanning"])

    assert f"<!-- {GROUP_MARKER_PREFIX}Trivy/CVE-2024-9999 -->" in spec.body
    assert f"<!-- {MARKER_PREFIX}1 -->" in spec.body
    assert "CVE-2024-9999" in spec.title
    assert "CVE-2024-9999" in spec.body
    assert "code-scanning" in spec.labels
    # No alert number in title — title is stable across alert-number changes.
    assert "(alert #" not in spec.title


def test_build_group_issue_spec_renders_all_alert_instances() -> None:
    """Both alert links and both locations must appear in the issue body."""
    alert1 = _alert(1, location="/opt/venv:42")
    alert2 = _alert(2, location="/home/user/.cache/uv:7")
    grp = AlertGroup(
        tool="Trivy",
        rule_id="CVE-2024-0001",
        rule_name="CVE-2024-0001",
        description="Pillow vulnerability",
        severity="high",
        alerts=(alert1, alert2),
    )
    spec = build_group_issue_spec(grp, labels=["security"])

    assert f"<!-- {MARKER_PREFIX}1 -->" in spec.body
    assert f"<!-- {MARKER_PREFIX}2 -->" in spec.body
    assert "/opt/venv:42" in spec.body
    assert "/home/user/.cache/uv:7" in spec.body
    assert alert1.html_url in spec.body
    assert alert2.html_url in spec.body


# ── group_alerts ───────────────────────────────────────────────


def test_group_alerts_groups_by_tool_and_rule_id() -> None:
    alerts = [_alert(1), _alert(2), _alert(3, rule_id="CVE-2024-0002")]
    groups = group_alerts(alerts)

    assert len(groups) == 2
    key1 = ("Trivy", "CVE-2024-0001")
    key2 = ("Trivy", "CVE-2024-0002")
    assert key1 in groups
    assert key2 in groups
    assert len(groups[key1].alerts) == 2
    assert len(groups[key2].alerts) == 1


def test_group_alerts_uses_highest_severity_for_group() -> None:
    alerts = [
        _alert(1, severity="low"),
        _alert(2, severity="critical"),
        _alert(3, severity="medium"),
    ]
    grp = group_alerts(alerts)[("Trivy", "CVE-2024-0001")]
    assert grp.severity == "critical"


def test_group_alerts_sorts_alerts_by_number() -> None:
    alerts = [_alert(3), _alert(1), _alert(2)]
    grp = group_alerts(alerts)[("Trivy", "CVE-2024-0001")]
    assert [a.number for a in grp.alerts] == [1, 2, 3]


# ── plan_sync — creation ───────────────────────────────────────


def test_plan_sync_two_alerts_same_cve_produce_one_create() -> None:
    """Two alert numbers for the same Trivy CVE must produce exactly one create."""
    alerts = [
        _alert(1, location="/opt/venv:1"),
        _alert(2, location="/home/.cache/uv:1"),
    ]
    plan = plan_sync(open_alerts=alerts, tracked_issues=[])

    assert len(plan.to_create) == 1
    assert plan.to_create[0].tool == "Trivy"
    assert plan.to_create[0].rule_id == "CVE-2024-0001"
    assert len(plan.to_create[0].alerts) == 2
    assert plan.to_update == []
    assert plan.to_close == []
    assert plan.to_close_duplicate == []


def test_plan_sync_creates_group_issue_for_untracked_open_alerts() -> None:
    # Two different CVEs: CVE-0001 is already tracked, CVE-0002 is not.
    alerts = [_alert(1, rule_id="CVE-2024-0001"), _alert(2, rule_id="CVE-2024-0002")]
    tracked = [_tracked(1, issue_number=100)]

    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    assert len(plan.to_create) == 1
    assert plan.to_create[0].rule_id == "CVE-2024-0002"
    assert plan.to_close == []


def test_plan_sync_different_cves_same_package_remain_separate_groups() -> None:
    """Different CVEs for the same package must never be merged into one group."""
    alerts = [
        _alert(1, rule_id="CVE-2024-0001"),
        _alert(2, rule_id="CVE-2024-0002"),
        _alert(3, rule_id="CVE-2024-0003"),
    ]
    plan = plan_sync(open_alerts=alerts, tracked_issues=[])

    assert len(plan.to_create) == 3
    rule_ids = {g.rule_id for g in plan.to_create}
    assert rule_ids == {"CVE-2024-0001", "CVE-2024-0002", "CVE-2024-0003"}


# ── plan_sync — closing ────────────────────────────────────────


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
    # A closed tracking issue for a still-open alert group must be re-created.
    alerts = [_alert(1)]
    tracked = [_tracked(1, issue_number=100, state="closed")]

    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    assert len(plan.to_create) == 1
    assert plan.to_create[0].rule_id == "CVE-2024-0001"
    assert plan.to_close == []


def test_plan_sync_resolving_one_instance_keeps_group_open_and_updates_body() -> None:
    """Resolving one of two alert instances keeps the group issue open (to_update)."""
    # Alert 2 is now resolved; alert 1 is still open.
    alerts = [_alert(1)]
    tracked_group = TrackedIssue(
        number=100,
        state="open",
        alert_number=1,
        group_key=("Trivy", "CVE-2024-0001"),
        alert_numbers=frozenset({1, 2}),
    )
    plan = plan_sync(open_alerts=alerts, tracked_issues=[tracked_group])

    assert plan.to_create == []
    assert len(plan.to_update) == 1
    assert plan.to_update[0][0].number == 100
    # Remaining group has only alert 1.
    assert len(plan.to_update[0][1].alerts) == 1
    assert plan.to_close == []
    assert plan.to_close_duplicate == []


def test_plan_sync_resolving_final_instance_closes_canonical_issue() -> None:
    """When all alerts in a group are resolved, the canonical issue is closed."""
    tracked_group = TrackedIssue(
        number=100,
        state="open",
        alert_number=1,
        group_key=("Trivy", "CVE-2024-0001"),
        alert_numbers=frozenset({1}),
    )
    plan = plan_sync(open_alerts=[], tracked_issues=[tracked_group])

    assert plan.to_create == []
    assert plan.to_update == []
    assert len(plan.to_close) == 1
    assert plan.to_close[0].number == 100
    assert plan.to_close_duplicate == []


# ── plan_sync — migration ──────────────────────────────────────


def test_plan_sync_legacy_singular_markers_migrate_without_losing_alert_references() -> None:
    """Legacy one-alert-per-issue trackers are migrated: oldest becomes canonical."""
    alerts = [_alert(1), _alert(2)]
    tracked = [
        _tracked(1, issue_number=100),  # legacy, singular marker for alert 1
        _tracked(2, issue_number=101),  # legacy, singular marker for alert 2
    ]
    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    assert plan.to_create == []
    # Issue 100 (lowest number) becomes canonical.
    assert len(plan.to_update) == 1
    assert plan.to_update[0][0].number == 100
    # Both alerts are included in the updated group body.
    assert len(plan.to_update[0][1].alerts) == 2
    # Issue 101 is marked as duplicate.
    assert len(plan.to_close_duplicate) == 1
    dup, canonical, grp = plan.to_close_duplicate[0]
    assert dup.number == 101
    assert canonical.number == 100
    assert grp.rule_id == "CVE-2024-0001"


def test_plan_sync_duplicate_trackers_produce_canonical_update_plus_closures() -> None:
    """Multiple open trackers for the same group → one update, rest closed as duplicate."""
    alerts = [_alert(1), _alert(2), _alert(3)]
    tracked = [
        _tracked(1, issue_number=50),  # oldest → canonical
        _tracked(2, issue_number=200),  # duplicate
        _tracked(3, issue_number=300),  # duplicate
    ]
    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    assert plan.to_create == []
    assert len(plan.to_update) == 1
    assert plan.to_update[0][0].number == 50
    dup_numbers = {dup.number for dup, _, _ in plan.to_close_duplicate}
    assert dup_numbers == {200, 300}


# ── plan_sync — idempotency ────────────────────────────────────


def test_plan_sync_is_idempotent_after_canonical_group_created() -> None:
    """Running plan_sync twice with the same state produces the same plan."""
    alerts = [_alert(1), _alert(2)]
    # Simulates a canonical group issue that was created on the first run.
    tracked_group = TrackedIssue(
        number=100,
        state="open",
        alert_number=1,
        group_key=("Trivy", "CVE-2024-0001"),
        alert_numbers=frozenset({1, 2}),
    )

    plan1 = plan_sync(open_alerts=alerts, tracked_issues=[tracked_group])
    plan2 = plan_sync(open_alerts=alerts, tracked_issues=[tracked_group])

    # Both runs produce identical plans (to_update is the only action, no creates/closes).
    assert plan1.to_create == plan2.to_create == []
    assert plan1.to_close == plan2.to_close == []
    assert plan1.to_close_duplicate == plan2.to_close_duplicate == []
    assert len(plan1.to_update) == len(plan2.to_update) == 1


# ── dry-run grouping ──────────────────────────────────────────


def test_plan_sync_dry_run_groups_creates_not_individual_alerts(
    capsys: object,
) -> None:
    """Dry-run: 20 Pillow-style alerts (2 locations each for 10 CVEs) yield 10 creates."""
    cves = [f"CVE-2024-{i:04d}" for i in range(10)]
    alerts = [
        _alert(i * 2 + loc, rule_id=cve, location=f"/path/{loc}:1")
        for i, cve in enumerate(cves)
        for loc in range(2)
    ]
    plan = plan_sync(open_alerts=alerts, tracked_issues=[])

    # 20 alerts, 10 CVEs → exactly 10 group creates.
    assert len(plan.to_create) == 10
    for grp in plan.to_create:
        assert len(grp.alerts) == 2


# ── acceptance fixtures ────────────────────────────────────────


def test_pillow_fixture_yields_ten_canonical_issues_not_twenty() -> None:
    """20 Pillow alerts (10 CVEs × 2 locations) → 10 canonical issues."""
    pillow_cves = [f"CVE-2024-{i:04d}" for i in range(10)]
    alerts = [
        _alert(
            number=i * 2 + loc,
            rule_id=cve,
            location="/opt/venv:1" if loc == 0 else "/home/.cache/uv:1",
        )
        for i, cve in enumerate(pillow_cves)
        for loc in range(2)
    ]
    plan = plan_sync(open_alerts=alerts, tracked_issues=[])

    assert len(plan.to_create) == 10
    assert all(len(g.alerts) == 2 for g in plan.to_create)


def test_dotnet_fixture_yields_five_canonical_issues_not_ten() -> None:
    """10 .NET alerts (5 CVEs × 2 locations) → 5 canonical issues."""
    dotnet_cves = [f"GHSA-dotnet-{i:04d}" for i in range(5)]
    alerts = [
        _alert(
            number=i * 2 + loc,
            tool="Trivy",
            rule_id=cve,
            location="/azure/functions/host:1" if loc == 0 else "/usr/share/dotnet:1",
        )
        for i, cve in enumerate(dotnet_cves)
        for loc in range(2)
    ]
    plan = plan_sync(open_alerts=alerts, tracked_issues=[])

    assert len(plan.to_create) == 5
    assert all(len(g.alerts) == 2 for g in plan.to_create)


# ── filter_alerts_by_severity ─────────────────────────────────


def test_filter_alerts_by_severity_keeps_all_when_no_filter() -> None:
    alerts = [_alert(1, severity="low"), _alert(2, severity="high")]
    assert filter_alerts_by_severity(alerts, allowed=frozenset()) == alerts


def test_filter_alerts_by_severity_is_case_insensitive() -> None:
    alerts = [_alert(1, severity="LOW"), _alert(2, severity="High")]
    kept = filter_alerts_by_severity(alerts, allowed=frozenset({"high", "critical"}))
    assert [a.number for a in kept] == [2]

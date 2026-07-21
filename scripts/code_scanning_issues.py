"""Sync open GitHub Code Scanning alerts into tracked GitHub issues.

Every open Code Scanning alert (Trivy, Semgrep, pip-audit, CodeQL — anything
that uploads SARIF) is mirrored into a GitHub issue so security findings land
in the backlog and get triaged like any other work, just like CVEs.

The sync is idempotent and reconciling:

* Alerts are grouped by ``(tool, rule_id)``. Each group maps to exactly one
  canonical tracking issue that lists all active alert instances and locations.
* A stable group marker ``<!-- code-scanning-group:TOOL/RULE_ID -->`` identifies
  the canonical issue. Individual ``<!-- code-scanning-alert:N -->`` markers are
  also embedded for backward compatibility with older singular trackers.
* When all alerts in a group are fixed or dismissed, the canonical issue is
  closed automatically.
* During migration, the oldest open tracking issue for a group is selected as
  canonical; duplicates are closed as not-planned.
* A later recurrence of the same ``(tool, rule_id)`` reopens/updates the
  canonical tracker instead of creating one issue per location.

Pure planning logic (``plan_sync`` / ``build_group_issue_spec``) is separated
from the GitHub I/O boundary so it is testable without network access.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

MARKER_PREFIX = "code-scanning-alert:"
GROUP_MARKER_PREFIX = "code-scanning-group:"
DEFAULT_LABELS: tuple[str, ...] = ("security", "code-scanning")
_TITLE_MAX_DESC = 100
_SEVERITY_ORDER: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "unspecified": 0,
}


@dataclass(frozen=True)
class CodeScanningAlert:
    number: int
    state: str
    tool: str
    rule_id: str
    rule_name: str
    description: str
    severity: str
    html_url: str
    location: str


@dataclass(frozen=True)
class AlertGroup:
    """A set of Code Scanning alerts that share the same ``(tool, rule_id)``."""

    tool: str
    rule_id: str
    rule_name: str
    description: str
    severity: str
    alerts: tuple[CodeScanningAlert, ...]


@dataclass(frozen=True)
class TrackedIssue:
    number: int
    state: str
    alert_number: int  # primary alert number for backward compat; 0 when absent
    group_key: tuple[str, str] | None = None  # (tool, rule_id) from group marker
    alert_numbers: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class IssueSpec:
    title: str
    body: str
    labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SyncPlan:
    to_create: list[AlertGroup]
    to_update: list[tuple[TrackedIssue, AlertGroup]]
    to_close: list[TrackedIssue]
    # Each tuple: (duplicate_issue, canonical_issue, group) for migration comments.
    to_close_duplicate: list[tuple[TrackedIssue, TrackedIssue, AlertGroup]] = field(
        default_factory=list
    )


# ── Pure logic ─────────────────────────────────────────────────


def parse_alert_marker(body: str) -> int | None:
    """Extract the first alert number embedded in an issue body, or ``None``."""
    marker = f"<!-- {MARKER_PREFIX}"
    start = body.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = body.find(" -->", start)
    if end == -1:
        return None
    raw = body[start:end].strip()
    if not raw.isdigit():
        return None
    return int(raw)


def parse_all_alert_markers(body: str) -> frozenset[int]:
    """Extract all ``<!-- code-scanning-alert:N -->`` numbers from a body."""
    results: set[int] = set()
    marker = f"<!-- {MARKER_PREFIX}"
    pos = 0
    while True:
        start = body.find(marker, pos)
        if start == -1:
            break
        start += len(marker)
        end = body.find(" -->", start)
        if end == -1:
            break
        raw = body[start:end].strip()
        if raw.isdigit():
            results.add(int(raw))
        pos = end + 4
    return frozenset(results)


def parse_group_marker(body: str) -> tuple[str, str] | None:
    """Extract ``(tool, rule_id)`` from the group marker, or ``None``.

    The marker format is ``<!-- code-scanning-group:TOOL/RULE_ID -->``.
    The tool and rule_id are split on the *first* slash only, so rule IDs
    containing slashes (e.g. Semgrep rule paths) are preserved intact.
    """
    marker = f"<!-- {GROUP_MARKER_PREFIX}"
    start = body.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = body.find(" -->", start)
    if end == -1:
        return None
    raw = body[start:end].strip()
    if "/" not in raw:
        return None
    tool, _, rule_id = raw.partition("/")
    return (tool, rule_id) if tool and rule_id else None


def _truncate(text: str, limit: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _max_severity(severities: Iterable[str]) -> str:
    """Return the highest severity label from a collection."""
    best = "unspecified"
    best_rank = -1
    for sev in severities:
        rank = _SEVERITY_ORDER.get(sev.lower(), 0)
        if rank > best_rank:
            best_rank = rank
            best = sev.lower()
    return best


def group_alerts(alerts: list[CodeScanningAlert]) -> dict[tuple[str, str], AlertGroup]:
    """Group alerts by ``(tool, rule_id)``, returning a mapping keyed by that pair."""
    raw: dict[tuple[str, str], list[CodeScanningAlert]] = {}
    for alert in alerts:
        key = (alert.tool, alert.rule_id)
        raw.setdefault(key, []).append(alert)

    result: dict[tuple[str, str], AlertGroup] = {}
    for key, items in raw.items():
        first = min(items, key=lambda a: a.number)
        result[key] = AlertGroup(
            tool=key[0],
            rule_id=key[1],
            rule_name=first.rule_name,
            description=first.description,
            severity=_max_severity(a.severity for a in items),
            alerts=tuple(sorted(items, key=lambda a: a.number)),
        )
    return result


def build_issue_spec(alert: CodeScanningAlert, *, labels: list[str]) -> IssueSpec:
    """Render a stable tracking issue for a single code scanning alert.

    Kept for backward compatibility. Prefer ``build_group_issue_spec`` for
    new code paths.
    """
    short_desc = _truncate(alert.description or alert.rule_name or alert.rule_id, _TITLE_MAX_DESC)
    title = f"[security] {alert.tool} {alert.rule_id}: {short_desc} (alert #{alert.number})"
    body = (
        f"<!-- {MARKER_PREFIX}{alert.number} -->\n"
        "Automated tracking issue for an open GitHub Code Scanning alert.\n\n"
        f"- **Tool:** {alert.tool}\n"
        f"- **Rule:** `{alert.rule_id}` — {alert.rule_name}\n"
        f"- **Severity:** {alert.severity or 'unspecified'}\n"
        f"- **Location:** `{alert.location}`\n"
        f"- **Alert:** [#{alert.number}]({alert.html_url})\n\n"
        f"{alert.description}\n\n"
        "---\n"
        "This issue is managed by the Code Scanning issue sync. It is closed "
        "automatically once the alert is fixed or dismissed. Do not edit the "
        "marker comment above."
    )
    return IssueSpec(title=title, body=body, labels=list(labels))


def build_group_issue_spec(group: AlertGroup, *, labels: list[str]) -> IssueSpec:
    """Render a canonical tracking issue for a ``(tool, rule_id)`` alert group.

    The body embeds:
    * A stable group marker for canonical identity across runs.
    * Individual alert markers (``<!-- code-scanning-alert:N -->``) for
      backward compatibility with tooling that reads singular markers.
    * A human-readable list of every active alert instance and location.
    """
    short_desc = _truncate(group.description or group.rule_name or group.rule_id, _TITLE_MAX_DESC)
    title = f"[security] {group.tool} {group.rule_id}: {short_desc}"

    group_marker = f"<!-- {GROUP_MARKER_PREFIX}{group.tool}/{group.rule_id} -->"
    alert_markers = "\n".join(f"<!-- {MARKER_PREFIX}{a.number} -->" for a in group.alerts)
    alert_lines = "\n".join(
        f"- Alert [#{a.number}]({a.html_url}) — `{a.location}` (severity: {a.severity})"
        for a in group.alerts
    )

    body = (
        f"{group_marker}\n"
        f"{alert_markers}\n"
        "Automated tracking issue for open GitHub Code Scanning alerts.\n\n"
        f"- **Tool:** {group.tool}\n"
        f"- **Rule:** `{group.rule_id}` — {group.rule_name}\n"
        f"- **Severity:** {group.severity or 'unspecified'}\n\n"
        "## Open Alert Instances\n\n"
        f"{alert_lines}\n\n"
        f"{group.description}\n\n"
        "---\n"
        "This issue is managed by the Code Scanning issue sync. It is closed "
        "automatically once all alerts in this group are fixed or dismissed. "
        "Do not edit the marker comments above."
    )
    return IssueSpec(title=title, body=body, labels=list(labels))


def plan_sync(
    *,
    open_alerts: list[CodeScanningAlert],
    tracked_issues: list[TrackedIssue],
) -> SyncPlan:
    """Decide which group issues to create, update, and close.

    Grouping key: ``(tool, rule_id)``.

    * **Create** a canonical issue for every group that has no open tracker.
    * **Update** the canonical (oldest-by-issue-number) tracker for every group
      that already has an open tracker, reflecting the current alert instances.
    * **Close duplicates** — any non-canonical open trackers for the same group
      (migration path from the previous one-issue-per-alert design).
    * **Close** open trackers whose entire alert group is no longer open.

    Legacy trackers (singular ``<!-- code-scanning-alert:N -->`` markers, no
    group marker) are reconciled by looking up their alert number in the current
    open-alert set to infer the group key.
    """
    open_groups = group_alerts(open_alerts)
    alert_to_group: dict[int, tuple[str, str]] = {
        a.number: (grp.tool, grp.rule_id) for grp in open_groups.values() for a in grp.alerts
    }

    group_to_trackers: dict[tuple[str, str], list[TrackedIssue]] = {}
    resolved_tracked: list[TrackedIssue] = []

    for ti in tracked_issues:
        if ti.state != "open":
            continue

        key: tuple[str, str] | None = ti.group_key

        if key is None:
            # Legacy tracker: infer group from embedded alert numbers.
            all_nums: frozenset[int] = ti.alert_numbers
            if ti.alert_number:
                all_nums = all_nums | {ti.alert_number}
            for an in sorted(all_nums):
                if an in alert_to_group:
                    key = alert_to_group[an]
                    break

        if key is not None:
            if key in open_groups:
                group_to_trackers.setdefault(key, []).append(ti)
            else:
                resolved_tracked.append(ti)
        else:
            resolved_tracked.append(ti)

    to_create: list[AlertGroup] = []
    to_update: list[tuple[TrackedIssue, AlertGroup]] = []
    to_close_duplicate: list[tuple[TrackedIssue, TrackedIssue, AlertGroup]] = []

    for key, grp in open_groups.items():
        trackers = group_to_trackers.get(key, [])
        if not trackers:
            to_create.append(grp)
        else:
            canonical = min(trackers, key=lambda t: t.number)
            to_update.append((canonical, grp))
            for ti in trackers:
                if ti is not canonical:
                    to_close_duplicate.append((ti, canonical, grp))

    return SyncPlan(
        to_create=to_create,
        to_update=to_update,
        to_close=resolved_tracked,
        to_close_duplicate=to_close_duplicate,
    )


def filter_alerts_by_severity(
    alerts: list[CodeScanningAlert],
    *,
    allowed: frozenset[str],
) -> list[CodeScanningAlert]:
    """Keep alerts whose severity is in ``allowed``; empty set keeps all."""
    if not allowed:
        return alerts
    normalised = frozenset(level.lower() for level in allowed)
    return [alert for alert in alerts if alert.severity.lower() in normalised]


# ── GitHub I/O boundary ────────────────────────────────────────


def _github_api(
    *,
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> Any:
    url = f"https://api.github.com{path}"
    payload = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url=url, data=payload, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8")) if data else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"GitHub API error {exc.code} on {method} {path}: {detail}") from exc


def _fetch_paginated(token: str, path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page = 1
    max_pages = 50  # bounded: 50 * 100 = 5000 items is far beyond any real backlog
    while page <= max_pages:
        separator = "&" if "?" in path else "?"
        page_path = f"{path}{separator}per_page=100&page={page}"
        batch = _github_api(token=token, method="GET", path=page_path)
        if not isinstance(batch, list) or not batch:
            break
        results.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return results


def _alert_severity(rule: dict[str, Any]) -> str:
    # Prefer security severity (Trivy/CodeQL security rules), fall back to the
    # generic rule severity that Semgrep/style rules carry.
    security = rule.get("security_severity_level")
    if isinstance(security, str) and security:
        return security
    generic = rule.get("severity")
    return generic if isinstance(generic, str) and generic else "unspecified"


def _alert_location(instance: dict[str, Any]) -> str:
    location = instance.get("location") if isinstance(instance, dict) else None
    if not isinstance(location, dict):
        return "unknown"
    path = str(location.get("path", "unknown"))
    start_line = location.get("start_line")
    return f"{path}:{start_line}" if start_line is not None else path


def load_open_alerts(*, token: str, owner: str, repo: str) -> list[CodeScanningAlert]:
    raw = _fetch_paginated(token, f"/repos/{owner}/{repo}/code-scanning/alerts?state=open")
    alerts: list[CodeScanningAlert] = []
    for item in raw:
        rule = item.get("rule", {}) if isinstance(item.get("rule"), dict) else {}
        tool = item.get("tool", {}) if isinstance(item.get("tool"), dict) else {}
        instance = (
            item.get("most_recent_instance", {})
            if isinstance(item.get("most_recent_instance"), dict)
            else {}
        )
        message = instance.get("message", {}) if isinstance(instance.get("message"), dict) else {}
        description = str(
            rule.get("description") or message.get("text") or rule.get("name") or ""
        ).strip()
        alerts.append(
            CodeScanningAlert(
                number=int(item["number"]),
                state=str(item.get("state", "open")),
                tool=str(tool.get("name", "unknown")),
                rule_id=str(rule.get("id") or rule.get("name") or "unknown"),
                rule_name=str(rule.get("name") or rule.get("id") or "unknown"),
                description=description,
                severity=_alert_severity(rule),
                html_url=str(item.get("html_url", "")),
                location=_alert_location(instance),
            )
        )
    return alerts


def load_tracked_issues(*, token: str, owner: str, repo: str, label: str) -> list[TrackedIssue]:
    raw = _fetch_paginated(token, f"/repos/{owner}/{repo}/issues?state=all&labels={label}")
    tracked: list[TrackedIssue] = []
    for issue in raw:
        if "pull_request" in issue:
            continue
        body = str(issue.get("body") or "")
        group_key = parse_group_marker(body)
        alert_numbers = parse_all_alert_markers(body)
        # Accept issues that have at least one recognised marker (group or singular alert).
        if group_key is None and not alert_numbers:
            continue
        primary = min(alert_numbers) if alert_numbers else 0
        tracked.append(
            TrackedIssue(
                number=int(issue["number"]),
                state=str(issue.get("state", "open")),
                alert_number=primary,
                group_key=group_key,
                alert_numbers=alert_numbers,
            )
        )
    return tracked


def create_issue(*, token: str, owner: str, repo: str, spec: IssueSpec) -> int:
    result = _github_api(
        token=token,
        method="POST",
        path=f"/repos/{owner}/{repo}/issues",
        body={"title": spec.title, "body": spec.body, "labels": spec.labels},
    )
    return int(result["number"]) if isinstance(result, dict) else 0


def update_issue(*, token: str, owner: str, repo: str, issue_number: int, spec: IssueSpec) -> None:
    """Update the title and body of an existing tracking issue."""
    _github_api(
        token=token,
        method="PATCH",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}",
        body={"title": spec.title, "body": spec.body},
    )


def close_issue(*, token: str, owner: str, repo: str, issue_number: int, comment: str) -> None:
    _github_api(
        token=token,
        method="POST",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        body={"body": comment},
    )
    _github_api(
        token=token,
        method="PATCH",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}",
        body={"state": "closed", "state_reason": "completed"},
    )


def close_issue_as_duplicate(
    *,
    token: str,
    owner: str,
    repo: str,
    issue_number: int,
    canonical_issue_number: int,
    group: AlertGroup,
) -> None:
    """Close a non-canonical tracking issue that has been superseded by a group tracker."""
    _github_api(
        token=token,
        method="POST",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        body={
            "body": (
                f"This tracking issue is a duplicate of the canonical group tracker "
                f"#{canonical_issue_number} for `{group.tool}` rule `{group.rule_id}`. "
                "Closing as not-planned (duplicate) during migration to grouped tracking."
            )
        },
    )
    _github_api(
        token=token,
        method="PATCH",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}",
        body={"state": "closed", "state_reason": "not_planned"},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--label",
        default="code-scanning",
        help="Marker label used to find/manage tracking issues.",
    )
    parser.add_argument(
        "--severity",
        default="",
        help="Comma-separated severities to include (e.g. 'critical,high'); empty = all.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise ValueError("GITHUB_TOKEN is required")

    labels = [args.label, *(lbl for lbl in DEFAULT_LABELS if lbl != args.label)]
    allowed = frozenset(part.strip().lower() for part in args.severity.split(",") if part.strip())

    alerts = filter_alerts_by_severity(
        load_open_alerts(token=token, owner=args.owner, repo=args.repo),
        allowed=allowed,
    )
    tracked = load_tracked_issues(token=token, owner=args.owner, repo=args.repo, label=args.label)
    plan = plan_sync(open_alerts=alerts, tracked_issues=tracked)

    print(
        f"code-scanning sync: open_alerts={len(alerts)} tracked={len(tracked)} "
        f"open_groups={len(plan.to_create) + len(plan.to_update)} "
        f"to_create={len(plan.to_create)} to_update={len(plan.to_update)} "
        f"to_close={len(plan.to_close)} to_close_duplicate={len(plan.to_close_duplicate)}"
    )

    if args.dry_run:
        for grp in plan.to_create:
            alert_nums = ", ".join(f"#{a.number}" for a in grp.alerts)
            print(
                f"- would create: {grp.tool} {grp.rule_id} "
                f"({len(grp.alerts)} instance(s): {alert_nums})"
            )
        for canonical, grp in plan.to_update:
            alert_nums = ", ".join(f"#{a.number}" for a in grp.alerts)
            print(
                f"- would update: issue #{canonical.number} for {grp.tool} {grp.rule_id} "
                f"({len(grp.alerts)} instance(s): {alert_nums})"
            )
        for issue in plan.to_close:
            print(f"- would close: issue #{issue.number} (all alerts in group resolved)")
        for issue in plan.to_close_duplicate:
            print(
                f"- would close-duplicate: issue #{issue[0].number} "
                f"(superseded by canonical group tracker #{issue[1].number} "
                f"for {issue[2].tool} {issue[2].rule_id})"
            )
        print("dry-run enabled; no issue changes were performed")
        return 0

    for grp in plan.to_create:
        spec = build_group_issue_spec(grp, labels=labels)
        number = create_issue(token=token, owner=args.owner, repo=args.repo, spec=spec)
        alert_nums = ", ".join(f"#{a.number}" for a in grp.alerts)
        print(
            f"created issue #{number} for {grp.tool} {grp.rule_id} "
            f"({len(grp.alerts)} instance(s): {alert_nums})"
        )

    for canonical, grp in plan.to_update:
        spec = build_group_issue_spec(grp, labels=labels)
        update_issue(
            token=token,
            owner=args.owner,
            repo=args.repo,
            issue_number=canonical.number,
            spec=spec,
        )
        alert_nums = ", ".join(f"#{a.number}" for a in grp.alerts)
        print(
            f"updated issue #{canonical.number} for {grp.tool} {grp.rule_id} "
            f"({len(grp.alerts)} instance(s): {alert_nums})"
        )

    for dup, canonical, grp in plan.to_close_duplicate:
        close_issue_as_duplicate(
            token=token,
            owner=args.owner,
            repo=args.repo,
            issue_number=dup.number,
            canonical_issue_number=canonical.number,
            group=grp,
        )
        print(
            f"closed duplicate issue #{dup.number} "
            f"(canonical: #{canonical.number} for {grp.tool} {grp.rule_id})"
        )

    for issue in plan.to_close:
        close_issue(
            token=token,
            owner=args.owner,
            repo=args.repo,
            issue_number=issue.number,
            comment=(
                "All Code Scanning alerts in this group are no longer open "
                "(fixed or dismissed); closing this tracking issue automatically."
            ),
        )
        print(f"closed issue #{issue.number} (group fully resolved)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Sync open GitHub Code Scanning alerts into tracked GitHub issues.

Every open Code Scanning alert (Trivy, Semgrep, pip-audit, CodeQL — anything
that uploads SARIF) is mirrored into a GitHub issue so security findings land
in the backlog and get triaged like any other work, just like CVEs.

The sync is idempotent and reconciling:

* Each issue embeds a hidden marker ``<!-- code-scanning-alert:N -->`` so a
  re-run never creates a duplicate.
* When an alert is fixed or dismissed (no longer open), its tracking issue is
  closed automatically.

Pure planning logic (``plan_sync`` / ``build_issue_spec``) is separated from the
GitHub I/O boundary so it is testable without network access.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

MARKER_PREFIX = "code-scanning-alert:"
DEFAULT_LABELS: tuple[str, ...] = ("security", "code-scanning")
_TITLE_MAX_DESC = 100


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
class TrackedIssue:
    number: int
    state: str
    alert_number: int


@dataclass(frozen=True)
class IssueSpec:
    title: str
    body: str
    labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SyncPlan:
    to_create: list[CodeScanningAlert]
    to_close: list[TrackedIssue]


# ── Pure logic ─────────────────────────────────────────────────


def parse_alert_marker(body: str) -> int | None:
    """Extract the alert number embedded in an issue body, or ``None``."""
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


def _truncate(text: str, limit: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_issue_spec(alert: CodeScanningAlert, *, labels: list[str]) -> IssueSpec:
    """Render a stable, deduplicable tracking issue for a code scanning alert."""
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


def plan_sync(
    *,
    open_alerts: list[CodeScanningAlert],
    tracked_issues: list[TrackedIssue],
) -> SyncPlan:
    """Decide which issues to create and which to close.

    * Create a tracking issue for every open alert without an *open* issue.
    * Close every *open* tracking issue whose alert is no longer open.
    """
    open_tracked_numbers = {issue.alert_number for issue in tracked_issues if issue.state == "open"}
    open_alert_numbers = {alert.number for alert in open_alerts}

    to_create = [alert for alert in open_alerts if alert.number not in open_tracked_numbers]
    to_close = [
        issue
        for issue in tracked_issues
        if issue.state == "open" and issue.alert_number not in open_alert_numbers
    ]
    return SyncPlan(to_create=to_create, to_close=to_close)


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
        alert_number = parse_alert_marker(str(issue.get("body") or ""))
        if alert_number is None:
            continue
        tracked.append(
            TrackedIssue(
                number=int(issue["number"]),
                state=str(issue.get("state", "open")),
                alert_number=alert_number,
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
        f"to_create={len(plan.to_create)} to_close={len(plan.to_close)}"
    )

    if args.dry_run:
        for alert in plan.to_create:
            print(f"- would create: alert #{alert.number} {alert.tool} {alert.rule_id}")
        for issue in plan.to_close:
            print(f"- would close: issue #{issue.number} (alert #{issue.alert_number} resolved)")
        print("dry-run enabled; no issue changes were performed")
        return 0

    for alert in plan.to_create:
        spec = build_issue_spec(alert, labels=labels)
        number = create_issue(token=token, owner=args.owner, repo=args.repo, spec=spec)
        print(f"created issue #{number} for alert #{alert.number}")

    for issue in plan.to_close:
        close_issue(
            token=token,
            owner=args.owner,
            repo=args.repo,
            issue_number=issue.number,
            comment=(
                f"Code Scanning alert #{issue.alert_number} is no longer open "
                "(fixed or dismissed); closing this tracking issue automatically."
            ),
        )
        print(f"closed issue #{issue.number} (alert #{issue.alert_number} resolved)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

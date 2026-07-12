from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

MARKER_RE = re.compile(r"<!--\s*code-scanning-alert:(\d+)\s*-->", re.IGNORECASE)


@dataclass(frozen=True)
class CodeScanningAlert:
    number: int
    html_url: str
    rule_id: str
    rule_description: str
    tool_name: str
    severity: str


@dataclass(frozen=True)
class TrackedIssue:
    number: int
    state: str
    title: str
    body: str
    labels: tuple[str, ...]

    @property
    def alert_number(self) -> int | None:
        match = MARKER_RE.search(self.body)
        if not match:
            return None
        return int(match.group(1))


@dataclass(frozen=True)
class IssueSpec:
    alert_number: int
    title: str
    body: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class SyncPlan:
    create: tuple[IssueSpec, ...]
    reopen: tuple[tuple[int, IssueSpec], ...]
    close: tuple[int, ...]


def build_issue_spec(*, alert: CodeScanningAlert, label: str) -> IssueSpec:
    title = f"[code-scanning] {alert.tool_name}: {alert.rule_id} (alert #{alert.number})"
    body = "\n".join(
        [
            f"Tracks GitHub Code Scanning alert #{alert.number}.",
            "",
            f"- Tool: `{alert.tool_name}`",
            f"- Rule: `{alert.rule_id}`",
            f"- Severity: `{alert.severity}`",
            f"- Alert: {alert.html_url}",
            "",
            "Auto-managed by `.github/workflows/code-scanning-issues.yml`.",
            f"<!-- code-scanning-alert:{alert.number} -->",
        ]
    )
    return IssueSpec(alert_number=alert.number, title=title, body=body, labels=(label, "security"))


def plan_sync(
    *,
    open_alerts: tuple[CodeScanningAlert, ...],
    tracked_issues: tuple[TrackedIssue, ...],
    label: str,
) -> SyncPlan:
    issues_by_alert: dict[int, list[TrackedIssue]] = {}
    for issue in tracked_issues:
        alert_number = issue.alert_number
        if alert_number is None:
            continue
        issues_by_alert.setdefault(alert_number, []).append(issue)

    create: list[IssueSpec] = []
    reopen: list[tuple[int, IssueSpec]] = []
    open_alert_numbers = {alert.number for alert in open_alerts}

    for alert in open_alerts:
        matches = issues_by_alert.get(alert.number, [])
        open_match = next((issue for issue in matches if issue.state == "open"), None)
        if open_match is not None:
            continue

        spec = build_issue_spec(alert=alert, label=label)
        closed_match = next((issue for issue in matches if issue.state == "closed"), None)
        if closed_match is not None:
            reopen.append((closed_match.number, spec))
        else:
            create.append(spec)

    close: list[int] = []
    for issue in tracked_issues:
        alert_number = issue.alert_number
        if alert_number is None:
            continue
        if issue.state != "open":
            continue
        if alert_number not in open_alert_numbers:
            close.append(issue.number)

    return SyncPlan(
        create=tuple(sorted(create, key=lambda spec: spec.alert_number)),
        reopen=tuple(sorted(reopen, key=lambda item: item[1].alert_number)),
        close=tuple(sorted(set(close))),
    )


def _github_rest(
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
        "Authorization": "Bearer " + token,
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
        raise RuntimeError(f"GitHub REST error {exc.code} on {method} {path}: {detail}") from exc


def _fetch_paginated(*, token: str, path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        page_path = f"{path}{separator}per_page=100&page={page}"
        batch = _github_rest(token=token, method="GET", path=page_path)
        if not isinstance(batch, list) or not batch:
            break
        results.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
        page += 1
    return results


def _parse_alert(entry: dict[str, Any]) -> CodeScanningAlert | None:
    number = entry.get("number")
    if not isinstance(number, int):
        return None

    rule = entry.get("rule")
    rule_id = (
        str((rule or {}).get("id") or "unknown-rule") if isinstance(rule, dict) else "unknown-rule"
    )
    rule_description = str((rule or {}).get("description") or "") if isinstance(rule, dict) else ""

    tool = entry.get("tool")
    tool_name = (
        str((tool or {}).get("name") or "unknown-tool")
        if isinstance(tool, dict)
        else "unknown-tool"
    )

    severity = str(
        (entry.get("rule") or {}).get("severity")
        or entry.get("rule_security_severity_level")
        or "unknown"
    ).lower()

    html_url = str(entry.get("html_url") or "")
    return CodeScanningAlert(
        number=number,
        html_url=html_url,
        rule_id=rule_id,
        rule_description=rule_description,
        tool_name=tool_name,
        severity=severity,
    )


def fetch_open_alerts(
    *, token: str, owner: str, repo: str, severity: str | None = None
) -> tuple[CodeScanningAlert, ...]:
    query = f"/repos/{owner}/{repo}/code-scanning/alerts?state=open"
    if severity:
        query = f"{query}&severity={parse.quote(severity)}"
    raw_alerts = _fetch_paginated(token=token, path=query)

    parsed_alerts: list[CodeScanningAlert] = []
    for entry in raw_alerts:
        alert = _parse_alert(entry)
        if alert is None:
            continue
        if severity and alert.severity != severity.lower():
            continue
        parsed_alerts.append(alert)

    return tuple(sorted(parsed_alerts, key=lambda alert: alert.number))


def fetch_tracked_issues(
    *, token: str, owner: str, repo: str, label: str
) -> tuple[TrackedIssue, ...]:
    query = f"/repos/{owner}/{repo}/issues?state=all&labels={parse.quote(label)}"
    raw_issues = _fetch_paginated(token=token, path=query)

    tracked: list[TrackedIssue] = []
    for issue in raw_issues:
        if issue.get("pull_request"):
            continue
        number = issue.get("number")
        if not isinstance(number, int):
            continue

        labels = issue.get("labels", [])
        label_names = tuple(
            sorted(
                str(item.get("name"))
                for item in labels
                if isinstance(item, dict) and item.get("name")
            )
        )
        tracked.append(
            TrackedIssue(
                number=number,
                state=str(issue.get("state") or "open"),
                title=str(issue.get("title") or ""),
                body=str(issue.get("body") or ""),
                labels=label_names,
            )
        )

    return tuple(tracked)


def _create_issue(*, token: str, owner: str, repo: str, spec: IssueSpec, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] create issue for alert #{spec.alert_number}")
        return
    _github_rest(
        token=token,
        method="POST",
        path=f"/repos/{owner}/{repo}/issues",
        body={"title": spec.title, "body": spec.body, "labels": list(spec.labels)},
    )
    print(f"Created issue for alert #{spec.alert_number}")


def _reopen_issue(
    *, token: str, owner: str, repo: str, issue_number: int, spec: IssueSpec, dry_run: bool
) -> None:
    if dry_run:
        print(f"[dry-run] reopen issue #{issue_number} for alert #{spec.alert_number}")
        return
    _github_rest(
        token=token,
        method="PATCH",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}",
        body={
            "state": "open",
            "title": spec.title,
            "body": spec.body,
            "labels": list(spec.labels),
        },
    )
    print(f"Reopened issue #{issue_number} for alert #{spec.alert_number}")


def _close_issue(*, token: str, owner: str, repo: str, issue_number: int, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] close issue #{issue_number}")
        return
    _github_rest(
        token=token,
        method="PATCH",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}",
        body={"state": "closed"},
    )
    print(f"Closed issue #{issue_number} (alert resolved or dismissed)")


def sync_code_scanning_issues(
    *,
    token: str,
    owner: str,
    repo: str,
    label: str,
    severity: str | None,
    dry_run: bool,
) -> SyncPlan:
    open_alerts = fetch_open_alerts(token=token, owner=owner, repo=repo, severity=severity)
    tracked_issues = fetch_tracked_issues(token=token, owner=owner, repo=repo, label=label)
    plan = plan_sync(open_alerts=open_alerts, tracked_issues=tracked_issues, label=label)

    print(
        "Planned sync: "
        f"create={len(plan.create)} reopen={len(plan.reopen)} close={len(plan.close)} "
        f"(open_alerts={len(open_alerts)})"
    )

    for spec in plan.create:
        _create_issue(token=token, owner=owner, repo=repo, spec=spec, dry_run=dry_run)
    for issue_number, spec in plan.reopen:
        _reopen_issue(
            token=token,
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            spec=spec,
            dry_run=dry_run,
        )
    for issue_number in plan.close:
        _close_issue(
            token=token, owner=owner, repo=repo, issue_number=issue_number, dry_run=dry_run
        )

    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mirror Code Scanning alerts into tracked issues")
    parser.add_argument("--owner", required=True, help="Repository owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--label", default="code-scanning-alert", help="Label for tracking issues")
    parser.add_argument(
        "--severity",
        choices=("critical", "high", "medium", "low"),
        help="Optional severity filter",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print actions without mutating issues"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    sync_code_scanning_issues(
        token=token,
        owner=args.owner,
        repo=args.repo,
        label=args.label,
        severity=args.severity,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

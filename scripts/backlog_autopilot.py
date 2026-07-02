"""Budget-paced GitHub issue autopilot dispatcher.

This script selects a bounded number of open issues and (optionally) assigns
Copilot to them, while respecting pacing and quality guardrails.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib import error, request

COPILOT_ACTOR_ID = "BOT_kgDOC9w8XQ"


def _copilot_actor_id() -> str:
    return os.getenv("AUTOPILOT_COPILOT_ACTOR_ID", COPILOT_ACTOR_ID).strip() or COPILOT_ACTOR_ID


@dataclass(frozen=True)
class BudgetStatus:
    allowed_today: float
    spent: float
    can_spend: bool


@dataclass(frozen=True)
class IssueCandidate:
    number: int
    title: str
    labels: set[str]
    assignees: set[str]
    url: str


@dataclass(frozen=True)
class Config:
    owner: str
    repo: str
    token: str
    dry_run: bool
    monthly_budget_usd: float
    month_spend_used_usd: float
    reserve_ratio: float
    max_new_assignments: int
    max_open_autopilot_prs: int


def _days_in_month(today: date) -> int:
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    return (next_month - date(today.year, today.month, 1)).days


def compute_budget_status(
    *,
    today: date,
    monthly_budget_usd: float,
    month_spend_used_usd: float,
    reserve_ratio: float,
) -> BudgetStatus:
    automation_budget = monthly_budget_usd * max(0.0, 1.0 - reserve_ratio)
    month_days = _days_in_month(today)
    allowed_today = automation_budget * (today.day / month_days)
    allowed_today_rounded = round(allowed_today, 2)
    return BudgetStatus(
        allowed_today=allowed_today_rounded,
        spent=month_spend_used_usd,
        can_spend=month_spend_used_usd < allowed_today_rounded,
    )


# Labels that exclude an issue from autopilot auto-assignment:
#   epic         — trackers spanning many PRs, not a single agent task
#   no-autopilot — manual gate for work that needs human design/approval
#                  (infra, OpenTofu, CI/CD, workflows) or can't be validated
#                  autonomously right now
_AUTOPILOT_EXCLUDED_LABELS = frozenset({"epic", "no-autopilot"})


def issue_priority_score(labels: set[str]) -> int:
    """Score an issue for autopilot eligibility (higher = assigned sooner).

    Auto-assignment is MoSCoW-driven: only ``moscow:must`` and ``moscow:should``
    are eligible. ``moscow:could`` / ``moscow:wont`` / untagged issues score 0
    and are never auto-assigned, and any issue carrying an excluded label
    (see ``_AUTOPILOT_EXCLUDED_LABELS``) is skipped. Security floats to the top
    of its MoSCoW tier (floor: the top security item is never starved).
    ``priority:*`` labels only refine ordering within a tier; ``discovered`` is
    provenance-only and no longer affects the score.
    """
    # Epics and human-gated (`no-autopilot`) work are never auto-assigned.
    if labels & _AUTOPILOT_EXCLUDED_LABELS:
        return 0
    if "moscow:must" in labels:
        score = 2000
    elif "moscow:should" in labels:
        score = 1000
    else:
        return 0
    # Security floor: lift the top security item to the front of its tier.
    if "security" in labels:
        score += 500
    # Legacy priority hints refine ordering within a MoSCoW tier.
    if "priority:now" in labels:
        score += 100
    elif "priority:next" in labels:
        score += 50
    return score


def select_issues(
    issues: list[IssueCandidate],
    *,
    max_new_assignments: int,
) -> list[IssueCandidate]:
    eligible = [
        issue for issue in issues if issue_priority_score(issue.labels) > 0 and not issue.assignees
    ]
    ordered = sorted(
        eligible,
        # MoSCoW tier DESC (must > should), then OLDEST issue first within a
        # tier (lower number sorts ahead under reverse=True via the negation)
        # so agents drain the backlog bottom-up instead of grabbing the newest.
        key=lambda issue: (issue_priority_score(issue.labels), -issue.number),
        reverse=True,
    )
    return ordered[:max_new_assignments]


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
    while True:
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


def _github_graphql(*, token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = request.Request(
        url="https://api.github.com/graphql",
        data=payload,
        method="POST",
        headers=headers,
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            parsed = json.loads(data.decode("utf-8")) if data else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"GitHub GraphQL error {exc.code}: {detail}") from exc

    errors = parsed.get("errors")
    if errors:
        raise RuntimeError(f"GitHub GraphQL returned errors: {errors}")

    result = parsed.get("data")
    if not isinstance(result, dict):
        raise RuntimeError("GitHub GraphQL response missing 'data' object")
    return result


def load_open_issues(*, token: str, owner: str, repo: str) -> list[IssueCandidate]:
    raw_issues = _fetch_paginated(token, f"/repos/{owner}/{repo}/issues?state=open")
    out: list[IssueCandidate] = []
    for issue in raw_issues:
        # GitHub issues endpoint includes pull requests.
        if "pull_request" in issue:
            continue
        labels = {
            label.get("name", "") for label in issue.get("labels", []) if isinstance(label, dict)
        }
        assignees = {
            assignee.get("login", "")
            for assignee in issue.get("assignees", [])
            if isinstance(assignee, dict)
        }
        out.append(
            IssueCandidate(
                number=int(issue["number"]),
                title=str(issue.get("title", "")),
                labels=labels,
                assignees=assignees,
                url=str(issue.get("html_url", "")),
            )
        )
    return out


def count_open_copilot_prs(*, token: str, owner: str, repo: str) -> int:
    pulls = _fetch_paginated(token, f"/repos/{owner}/{repo}/pulls?state=open")
    count = 0
    for pr in pulls:
        user = pr.get("user")
        login = user.get("login", "") if isinstance(user, dict) else ""
        title = str(pr.get("title", ""))
        if login == "Copilot" or title.startswith("[WIP]"):
            count += 1
    return count


def assign_issue_to_copilot(*, token: str, owner: str, repo: str, issue_number: int) -> None:
    issue_data = _github_graphql(
        token=token,
        query=(
            "query AssignableIssue($owner: String!, $repo: String!, $number: Int!) {"
            " repository(owner: $owner, name: $repo) {"
            "   issue(number: $number) {"
            "     id"
            "     assignees(first: 100) { nodes { id login } }"
            "   }"
            " }"
            "}"
        ),
        variables={"owner": owner, "repo": repo, "number": issue_number},
    )
    repository = issue_data.get("repository")
    issue = repository.get("issue") if isinstance(repository, dict) else None
    if not isinstance(issue, dict):
        raise RuntimeError(f"Issue #{issue_number} not found for {owner}/{repo}")

    assignable_id = issue.get("id")
    if not isinstance(assignable_id, str) or not assignable_id:
        raise RuntimeError(f"Issue #{issue_number} missing assignable id")

    assignees_obj = issue.get("assignees")
    nodes = assignees_obj.get("nodes", []) if isinstance(assignees_obj, dict) else []
    existing_actor_ids: list[str] = []
    existing_actor_id_set: set[str] = set()
    existing_logins: set[str] = set()
    copilot_actor_id = _copilot_actor_id()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        actor_id = node.get("id")
        login = node.get("login")
        if isinstance(actor_id, str) and actor_id:
            existing_actor_ids.append(actor_id)
            existing_actor_id_set.add(actor_id)
        if isinstance(login, str) and login:
            existing_logins.add(login)

    if "Copilot" in existing_logins or copilot_actor_id in existing_actor_id_set:
        return

    actor_ids = list(dict.fromkeys([*existing_actor_ids, copilot_actor_id]))
    _github_graphql(
        token=token,
        query=(
            "mutation ReplaceActorsForAssignable($input: ReplaceActorsForAssignableInput!) {"
            "  replaceActorsForAssignable(input: $input) { __typename }"
            "}"
        ),
        variables={"input": {"assignableId": assignable_id, "actorIds": actor_ids}},
    )


def post_issue_comment(
    *,
    token: str,
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
) -> None:
    _github_api(
        token=token,
        method="POST",
        path=f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        body={"body": body},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--monthly-budget-usd", type=float, required=True)
    parser.add_argument("--month-spend-used-usd", type=float, required=True)
    parser.add_argument("--reserve-ratio", type=float, default=0.25)
    parser.add_argument("--max-new-assignments", type=int, default=2)
    parser.add_argument("--max-open-autopilot-prs", type=int, default=8)
    parser.add_argument("--today", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise ValueError("GITHUB_TOKEN is required")

    today = date.fromisoformat(args.today) if args.today else datetime.now(UTC).date()
    cfg = Config(
        owner=args.owner,
        repo=args.repo,
        token=token,
        dry_run=bool(args.dry_run),
        monthly_budget_usd=float(args.monthly_budget_usd),
        month_spend_used_usd=float(args.month_spend_used_usd),
        reserve_ratio=float(args.reserve_ratio),
        max_new_assignments=int(args.max_new_assignments),
        max_open_autopilot_prs=int(args.max_open_autopilot_prs),
    )

    budget = compute_budget_status(
        today=today,
        monthly_budget_usd=cfg.monthly_budget_usd,
        month_spend_used_usd=cfg.month_spend_used_usd,
        reserve_ratio=cfg.reserve_ratio,
    )
    if not budget.can_spend:
        print(
            f"budget_throttle: spent={budget.spent:.2f} allowed_today={budget.allowed_today:.2f}; "
            "no new assignments"
        )
        return 0

    open_autopilot_prs = count_open_copilot_prs(token=cfg.token, owner=cfg.owner, repo=cfg.repo)
    if open_autopilot_prs >= cfg.max_open_autopilot_prs:
        print(
            f"queue_throttle: open_autopilot_prs={open_autopilot_prs} "
            f">= max_open_autopilot_prs={cfg.max_open_autopilot_prs}; no new assignments"
        )
        return 0

    issues = load_open_issues(token=cfg.token, owner=cfg.owner, repo=cfg.repo)
    targets = select_issues(issues, max_new_assignments=cfg.max_new_assignments)

    if not targets:
        print("no eligible issues found")
        return 0

    print("selected issues:")
    for target in targets:
        print(f"- #{target.number} {target.title} ({target.url})")

    if cfg.dry_run:
        print("dry-run enabled; no assignment actions were performed")
        return 0

    for target in targets:
        assign_issue_to_copilot(
            token=cfg.token,
            owner=cfg.owner,
            repo=cfg.repo,
            issue_number=target.number,
        )
        post_issue_comment(
            token=cfg.token,
            owner=cfg.owner,
            repo=cfg.repo,
            issue_number=target.number,
            body=(
                "Autopilot dispatcher assigned Copilot under monthly pacing policy "
                f"(budget spent {budget.spent:.2f} / allowed today {budget.allowed_today:.2f})."
            ),
        )

    print(f"assigned {len(targets)} issue(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

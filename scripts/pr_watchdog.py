"""PR watchdog that tracks blockers and opinion-needed items on active autopilot PRs."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, request

# Mirrors the regex in .github/workflows/require-linked-issue.yml so the
# watchdog flags the same PRs the gate would reject (supports owner/repo#NNN).
_ISSUE_LINK_RE = re.compile(
    r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s+(?:[\w.-]+/[\w.-]+)?#\d+",
    re.IGNORECASE,
)


def body_links_issue(body: str | None) -> bool:
    """True when the PR body links a closing issue (closes/fixes/resolves #NNN)."""
    return bool(_ISSUE_LINK_RE.search(body or ""))


CHECK_FAILURE_CONCLUSIONS = {
    "failure",
    "timed_out",
    "cancelled",
    "action_required",
    "startup_failure",
    "stale",
}

COMMENT_MARKER = "<!-- pr-watchdog -->"


@dataclass(frozen=True)
class ReviewThread:
    author: str
    path: str
    url: str
    body: str


@dataclass(frozen=True)
class PRSummary:
    number: int
    url: str
    title: str
    failing_checks: tuple[str, ...]
    pending_checks: tuple[str, ...]
    unresolved_threads: tuple[ReviewThread, ...]
    missing_linked_issue: bool = False
    is_draft: bool = False

    @property
    def has_blockers(self) -> bool:
        return bool(self.failing_checks or self.unresolved_threads or self.missing_linked_issue)


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
        raise RuntimeError(f"GitHub REST error {exc.code} on {method} {path}: {detail}") from exc


def _github_graphql(*, token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = {"query": query, "variables": variables}
    result = _github_rest(token=token, method="POST", path="/graphql", body=payload)
    if not isinstance(result, dict):
        raise RuntimeError("GraphQL returned non-object response")
    if result.get("errors"):
        raise RuntimeError(f"GraphQL errors: {result['errors']}")
    return result


def _fetch_paginated(token: str, path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        page_path = f"{path}{separator}per_page=100&page={page}"
        batch = _github_rest(token=token, method="GET", path=page_path)
        if not isinstance(batch, list) or not batch:
            break
        results.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return results


def list_active_autopilot_prs(
    *, token: str, owner: str, repo: str, max_prs: int
) -> list[dict[str, Any]]:
    pulls = _fetch_paginated(token, f"/repos/{owner}/{repo}/pulls?state=open")
    active: list[dict[str, Any]] = []
    for pr in pulls:
        title = str(pr.get("title", ""))
        user = pr.get("user")
        login = user.get("login", "") if isinstance(user, dict) else ""
        if login == "Copilot" or title.startswith("[WIP]"):
            active.append(pr)
        if len(active) >= max_prs:
            break
    return active


def collect_check_status(
    *,
    token: str,
    owner: str,
    repo: str,
    head_sha: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    data = _github_rest(
        token=token,
        method="GET",
        path=f"/repos/{owner}/{repo}/commits/{head_sha}/check-runs?per_page=100",
    )
    checks = data.get("check_runs", []) if isinstance(data, dict) else []

    failing: list[str] = []
    pending: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name", "unknown"))
        status = str(check.get("status", ""))
        conclusion = str(check.get("conclusion", ""))
        if status != "completed":
            pending.append(name)
            continue
        if conclusion in CHECK_FAILURE_CONCLUSIONS:
            failing.append(name)

    return tuple(sorted(set(failing))), tuple(sorted(set(pending)))


def collect_unresolved_threads(
    *,
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
) -> tuple[ReviewThread, ...]:
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) {
            nodes {
              isResolved
              comments(first: 1) {
                nodes {
                  body
                  path
                  url
                  author { login }
                }
              }
            }
          }
        }
      }
    }
    """
    result = _github_graphql(
        token=token,
        query=query,
        variables={"owner": owner, "repo": repo, "number": pr_number},
    )
    repo_data = (result.get("data") or {}).get("repository") or {}
    pr_data = repo_data.get("pullRequest") or {}
    nodes = (pr_data.get("reviewThreads") or {}).get("nodes") or []

    unresolved: list[ReviewThread] = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("isResolved") is True:
            continue
        comments = (node.get("comments") or {}).get("nodes") or []
        first = comments[0] if comments else {}
        if not isinstance(first, dict):
            continue
        unresolved.append(
            ReviewThread(
                author=str((first.get("author") or {}).get("login", "unknown")),
                path=str(first.get("path") or ""),
                url=str(first.get("url") or ""),
                body=str(first.get("body") or ""),
            )
        )

    return tuple(unresolved)


def render_comment(summary: PRSummary) -> str:
    lines = [
        COMMENT_MARKER,
        "## PR Watchdog",
        "",
        f"PR: #{summary.number} — {summary.title}",
        f"Link: {summary.url}",
        "",
        "### Blockers",
    ]
    if summary.failing_checks:
        lines.append("- Failing checks:")
        for check in summary.failing_checks:
            lines.append(f"  - {check}")
    else:
        lines.append("- Failing checks: none")

    if summary.unresolved_threads:
        lines.append("- Unresolved review threads:")
        for thread in summary.unresolved_threads:
            lines.append(f"  - {thread.author} on {thread.path or 'unknown path'}: {thread.url}")
    else:
        lines.append("- Unresolved review threads: none")

    if summary.missing_linked_issue:
        lines.append("- Linked issue: MISSING — add `Closes #NNN` to the PR body")
    else:
        lines.append("- Linked issue: present")

    lines.append("")
    lines.append("### Needs Opinion")
    if summary.unresolved_threads:
        lines.append(
            "- Yes. There are unresolved review threads requiring maintainer judgment or approval."
        )
    else:
        lines.append("- No explicit opinion-needed threads currently open.")

    lines.append("")
    lines.append("### Check Progress")
    if summary.pending_checks:
        lines.append("- Pending checks:")
        for check in summary.pending_checks:
            lines.append(f"  - {check}")
    else:
        lines.append("- Pending checks: none")

    lines.append("")
    if summary.has_blockers:
        lines.append("Status: BLOCKED")
    elif summary.pending_checks:
        lines.append("Status: WAITING_ON_CI")
    elif summary.is_draft:
        lines.append(
            "Status: READY_TO_PROMOTE — no blockers; promote out of draft with `gh pr ready`"
        )
    else:
        lines.append("Status: READY_FOR_MAINTAINER_REVIEW")

    return "\n".join(lines)


def _find_existing_watchdog_comment(
    *,
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
) -> int | None:
    comments = _fetch_paginated(
        token, f"/repos/{owner}/{repo}/issues/{pr_number}/comments?sort=created"
    )
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = str(comment.get("body", ""))
        if COMMENT_MARKER in body:
            return int(comment["id"])
    return None


def upsert_watchdog_comment(
    *,
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
) -> None:
    existing_id = _find_existing_watchdog_comment(
        token=token,
        owner=owner,
        repo=repo,
        pr_number=pr_number,
    )
    if existing_id is None:
        _github_rest(
            token=token,
            method="POST",
            path=f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            body={"body": body},
        )
        return

    _github_rest(
        token=token,
        method="PATCH",
        path=f"/repos/{owner}/{repo}/issues/comments/{existing_id}",
        body={"body": body},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-prs", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise ValueError("GITHUB_TOKEN is required")

    pulls = list_active_autopilot_prs(
        token=token,
        owner=args.owner,
        repo=args.repo,
        max_prs=args.max_prs,
    )
    if not pulls:
        print("no active autopilot PRs found")
        return 0

    for pr in pulls:
        number = int(pr["number"])
        head = pr.get("head") or {}
        head_sha = str(head.get("sha", ""))
        failing, pending = collect_check_status(
            token=token,
            owner=args.owner,
            repo=args.repo,
            head_sha=head_sha,
        )
        unresolved = collect_unresolved_threads(
            token=token,
            owner=args.owner,
            repo=args.repo,
            pr_number=number,
        )
        summary = PRSummary(
            number=number,
            url=str(pr.get("html_url", "")),
            title=str(pr.get("title", "")),
            failing_checks=failing,
            pending_checks=pending,
            unresolved_threads=unresolved,
            missing_linked_issue=not body_links_issue(pr.get("body")),
            is_draft=bool(pr.get("draft")),
        )
        comment = render_comment(summary)

        print(
            f"#{summary.number} blockers={summary.has_blockers} pending={len(summary.pending_checks)}"
        )
        if args.dry_run:
            continue
        upsert_watchdog_comment(
            token=token,
            owner=args.owner,
            repo=args.repo,
            pr_number=summary.number,
            body=comment,
        )

    if args.dry_run:
        print("dry-run enabled; no comments were created or updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

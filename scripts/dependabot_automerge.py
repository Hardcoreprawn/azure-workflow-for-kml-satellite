"""Merge verified, mature GitHub Actions pin updates after complete hosted CI."""

from __future__ import annotations

import argparse
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml

from scripts.pr_watchdog import (
    CODE_REQUIRED_CHECKS,
    _fetch_paginated,
    _github_graphql,
    _github_rest,
)
from scripts.pr_watchdog import (
    REQUIRED_CHECKS as WATCHDOG_CHECKS,
)

REQUIRED_CHECKS = WATCHDOG_CHECKS | CODE_REQUIRED_CHECKS | {"Resolve dev image", "Trivyignore Expiry Check"}
OPTIONAL_SKIPS = {"Build Docker image", "Trivy"}
PIN = re.compile(r"(?P<prefix>\s*(?:-\s*)?uses:\s*)(?P<action>[\w.-]+/[\w./-]+)@(?P<sha>[a-f0-9]{40})(?:\s+#.*)?")
METADATA = re.compile(r"^---\n(.*?)^\.\.\.\s*$", re.MULTILINE | re.DOTALL)
VERSION = re.compile(r"\d+\.\d+\.\d+")
COOLDOWN = timedelta(days=3)


def candidate_blocker(pr: dict[str, Any], repository: str) -> str:
    if pr["user"]["login"] != "dependabot[bot]" or pr["state"] != "open" or pr["draft"]:
        return "not an open, ready Dependabot PR"
    if pr["base"]["ref"] != "main" or any(pr[side]["repo"]["full_name"] != repository for side in ("base", "head")):
        return "wrong base or fork"
    if not pr["head"]["ref"].startswith("dependabot/github_actions/"):
        return "not a GitHub Actions update"
    labels = {label["name"].lower() for label in pr["labels"]}
    if labels & {"security", "do-not-merge", "hold"} or re.search(
        r"security update|GHSA-|CVE-", pr["body"] or "", re.I
    ):
        return "security update or owner hold requires manual review"
    if pr["mergeable_state"] != "clean":
        return "GitHub merge state is not clean"
    return ""


def updated_dependencies(commits: list[dict[str, Any]]) -> dict[str, str]:
    if len(commits) != 1:
        return {}
    item = commits[0]
    if (item.get("author") or {}).get("login") != "dependabot[bot]" or item["commit"]["verification"][
        "verified"
    ] is not True:
        return {}
    match = METADATA.search(item["commit"]["message"])
    if not match:
        return {}
    metadata = yaml.safe_load(match[1])
    rows = metadata.get("updated-dependencies") if isinstance(metadata, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("security-update"):
            return {}
        name, version = row.get("dependency-name"), row.get("dependency-version")
        if row.get("update-type") not in {"version-update:semver-patch", "version-update:semver-minor"}:
            return {}
        if not isinstance(name, str) or not isinstance(version, str) or not VERSION.fullmatch(version):
            return {}
        if name in result and result[name] != version:
            return {}
        result[name] = version
    return result


def action_pins(files: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for file in files:
        path = file["filename"]
        allowed = re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml|\.github/actions/.+/action\.ya?ml", path)
        if not allowed or file["status"] != "modified" or not file.get("patch"):
            return {}
        removed = [line[1:] for line in file["patch"].splitlines() if line.startswith("-")]
        added = [line[1:] for line in file["patch"].splitlines() if line.startswith("+")]
        if (
            not added
            or len(added) != file["additions"]
            or len(removed) != file["deletions"]
            or len(added) != len(removed)
        ):
            return {}
        for before, after in zip(removed, added, strict=True):
            old, new = PIN.fullmatch(before), PIN.fullmatch(after)
            if not old or not new or old["prefix"] != new["prefix"] or old["action"] != new["action"]:
                return {}
            name, sha = new["action"], new["sha"]
            if name in result and result[name] != sha:
                return {}
            result[name] = sha
    return result


def checks_blocker(runs: list[dict[str, Any]], sha: str) -> str:
    latest = {run["name"]: run for run in sorted(runs, key=lambda run: run["id"])}
    if missing := REQUIRED_CHECKS - latest.keys():
        return f"missing checks: {sorted(missing)}"
    for name, run in latest.items():
        if run["head_sha"] != sha or run["status"] != "completed":
            return f"stale or pending check: {name}"
        if name in REQUIRED_CHECKS and run["app"]["slug"] != "github-actions":
            return f"untrusted check provider: {name}"
        if run["conclusion"] != "success" and not (
            name in OPTIONAL_SKIPS and run["conclusion"] in {"neutral", "skipped"}
        ):
            return f"unsuccessful check: {name}"
    return ""


def release_old_enough(published_at: str, now: datetime) -> bool:
    return now - datetime.fromisoformat(published_at.replace("Z", "+00:00")) >= COOLDOWN


def fetch_checks(token: str, repository: str, sha: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for page in range(1, 101):
        data = _github_rest(
            token=token,
            method="GET",
            path=f"/repos/{repository}/commits/{sha}/check-runs?filter=latest&per_page=100&page={page}",
        )
        runs.extend(data["check_runs"])
        if len(runs) >= data["total_count"]:
            return runs
    raise RuntimeError("Check-run pagination exceeded 100 pages")


def review_blocker(token: str, repository: str, number: int) -> str:
    owner, repo = repository.split("/")
    result = _github_graphql(
        token=token,
        query="""query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) { pullRequest(number: $number) {
            reviewDecision
            reviewThreads(first: 100) { nodes { isResolved } pageInfo { hasNextPage } }
          } }
        }""",
        variables={"owner": owner, "repo": repo, "number": number},
    )["data"]["repository"]["pullRequest"]
    threads = result["reviewThreads"]
    if (
        result["reviewDecision"] in {"CHANGES_REQUESTED", "REVIEW_REQUIRED"}
        or threads["pageInfo"]["hasNextPage"]
        or any(not node["isResolved"] for node in threads["nodes"])
    ):
        return "outstanding review requirements or unresolved threads"
    reviews = _fetch_paginated(token, f"/repos/{repository}/pulls/{number}/reviews")
    latest = {}
    for review in reviews:
        if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[review["user"]["login"]] = review["state"]
    return "changes requested" if "CHANGES_REQUESTED" in latest.values() else ""


def release_blocker(token: str, dependencies: dict[str, str], pins: dict[str, str], now: datetime) -> str:
    for action, version in dependencies.items():
        owner, repo = action.split("/")[:2]
        release = _github_graphql(
            token=token,
            query="""query($owner: String!, $repo: String!, $tag: String!) {
              repository(owner: $owner, name: $repo) { release(tagName: $tag) {
                isDraft isPrerelease publishedAt tagCommit { oid }
              } }
            }""",
            variables={"owner": owner, "repo": repo, "tag": f"v{version}"},
        )["data"]["repository"]["release"]
        if release is None:
            return f"no published release: {action}; manual review required"
        if release["isDraft"] or release["isPrerelease"] or not release["publishedAt"]:
            return f"unpublished or prerelease: {action}"
        if not release_old_enough(release["publishedAt"], now):
            return f"release has not aged three days: {action}"
        if not release["tagCommit"] or release["tagCommit"]["oid"] != pins[action]:
            return f"release tag does not match pin: {action}"
    return ""


def process_pr(token: str, repository: str, number: int, *, apply: bool, now: datetime) -> str:
    path = f"/repos/{repository}/pulls/{number}"
    pr = _github_rest(token=token, method="GET", path=path)
    if blocker := candidate_blocker(pr, repository):
        return blocker
    commits = _fetch_paginated(token, f"{path}/commits")
    dependencies = updated_dependencies(commits)
    pins = action_pins(_fetch_paginated(token, f"{path}/files"))
    if not dependencies or dependencies.keys() != pins.keys() or commits[0]["sha"] != pr["head"]["sha"]:
        return "unsigned, major, mixed or non-pin update"
    alerts = _fetch_paginated(token, f"/repos/{repository}/dependabot/alerts?state=open")
    if any(alert["dependency"]["package"]["name"] in dependencies for alert in alerts):
        return "dependency has an open security alert; manual expedited review required"
    if blocker := release_blocker(token, dependencies, pins, now):
        return blocker
    sha = pr["head"]["sha"]
    comparison = _github_rest(token=token, method="GET", path=f"/repos/{repository}/compare/main...{sha}")
    if comparison["behind_by"] != 0:
        return "branch is behind main; Dependabot must rebase and rerun checks"
    if blocker := checks_blocker(fetch_checks(token, repository, sha), sha):
        return blocker
    statuses = _fetch_paginated(token, f"/repos/{repository}/commits/{sha}/statuses")
    latest_statuses = {item["context"]: item for item in sorted(statuses, key=lambda item: item["id"])}
    if any(item["state"] != "success" for item in latest_statuses.values()):
        return "pending or failed commit status"
    if blocker := review_blocker(token, repository, number):
        return blocker
    fresh = _github_rest(token=token, method="GET", path=path)
    if (
        fresh["head"]["sha"] != sha
        or fresh["base"]["sha"] != comparison["base_commit"]["sha"]
        or candidate_blocker(fresh, repository)
    ):
        return "PR changed during verification"
    if not apply:
        return "DRY_RUN: eligible for squash merge"
    result = _github_rest(token=token, method="PUT", path=f"{path}/merge", body={"sha": sha, "merge_method": "squash"})
    if result.get("merged") is not True:
        raise RuntimeError(f"GitHub refused to merge #{number}: {result.get('message')}")
    return f"MERGED: {result['sha']}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Merge eligible PRs; otherwise report only")
    args = parser.parse_args()
    token, repository = os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"]
    prs = _fetch_paginated(token, f"/repos/{repository}/pulls?state=open&base=main")
    for pr in prs:
        if pr["user"]["login"] == "dependabot[bot]":
            result = process_pr(token, repository, pr["number"], apply=args.apply, now=datetime.now(UTC))
            print(f"#{pr['number']}: {result}")
            # A merge changes main. Re-evaluate the remaining queue on the next run.
            if result.startswith("MERGED:"):
                break


if __name__ == "__main__":
    main()

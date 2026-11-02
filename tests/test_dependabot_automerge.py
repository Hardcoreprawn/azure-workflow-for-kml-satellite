from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from scripts import dependabot_automerge as merge

NOW = datetime(2026, 11, 2, tzinfo=UTC)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
MESSAGE = """Bump actions/setup-python

---
updated-dependencies:
- dependency-name: actions/setup-python
  dependency-version: 7.1.0
  update-type: version-update:semver-minor
...
"""


def candidate() -> dict:
    return {
        "number": 1,
        "state": "open",
        "draft": False,
        "user": {"login": "dependabot[bot]"},
        "base": {"ref": "main", "sha": OLD_SHA, "repo": {"full_name": "owner/repo"}},
        "head": {
            "sha": NEW_SHA,
            "ref": "dependabot/github_actions/actions/setup-python-7.1.0",
            "repo": {"full_name": "owner/repo"},
        },
        "labels": [],
        "body": "",
        "mergeable_state": "clean",
    }


def commit() -> dict:
    return {
        "sha": NEW_SHA,
        "author": {"login": "dependabot[bot]"},
        "commit": {"verification": {"verified": True}, "message": MESSAGE},
    }


def changed_file() -> dict:
    return {
        "filename": ".github/workflows/ci.yml",
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "patch": (
            "@@ -1 +1 @@\n"
            f"-      - uses: actions/setup-python@{OLD_SHA} # v7.0.0\n"
            f"+      - uses: actions/setup-python@{NEW_SHA} # v7.1.0"
        ),
    }


def checks() -> list[dict]:
    return [
        {
            "id": index,
            "name": name,
            "head_sha": NEW_SHA,
            "app": {"slug": "github-actions"},
            "status": "completed",
            "conclusion": "success",
        }
        for index, name in enumerate(sorted(merge.REQUIRED_CHECKS))
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("draft", True),
        ("state", "closed"),
        ("user", {"login": "human"}),
        ("labels", [{"name": "security"}]),
        ("labels", [{"name": "do-not-merge"}]),
        ("body", "This is a security update."),
        ("mergeable_state", "behind"),
    ],
)
def test_ineligible_pr_requires_manual_review(field: str, value: object) -> None:
    pr = candidate()
    pr[field] = value
    assert merge.candidate_blocker(pr, "owner/repo")


def test_forks_and_non_action_updates_are_manual() -> None:
    pr = candidate()
    pr["head"]["repo"]["full_name"] = "fork/repo"
    assert merge.candidate_blocker(pr, "owner/repo")
    pr = candidate()
    pr["head"]["ref"] = "dependabot/pip/pypdf-6.22.0"
    assert merge.candidate_blocker(pr, "owner/repo")


def test_signed_minor_and_grouped_patch_metadata_are_accepted() -> None:
    assert merge.updated_dependencies([commit()]) == {"actions/setup-python": "7.1.0"}
    grouped = commit()
    grouped["commit"]["message"] = MESSAGE.replace(
        "...\n",
        "- dependency-name: github/codeql-action/init\n"
        "  dependency-version: 4.39.1\n"
        "  update-type: version-update:semver-patch\n...\n",
    )
    assert len(merge.updated_dependencies([grouped])) == 2


@pytest.mark.parametrize(
    "message",
    [
        "",
        MESSAGE.replace("semver-minor", "semver-major"),
        MESSAGE.replace("7.1.0", "7.1.0-rc.1"),
        MESSAGE.replace("updated-dependencies:", "unknown:"),
        MESSAGE.replace("  update-type:", "  security-update: true\n  update-type:"),
    ],
)
def test_unknown_major_prerelease_and_security_metadata_are_manual(message: str) -> None:
    item = commit()
    item["commit"]["message"] = message
    assert merge.updated_dependencies([item]) == {}


def test_unsigned_or_human_commits_are_manual() -> None:
    item = commit()
    item["commit"]["verification"]["verified"] = False
    assert merge.updated_dependencies([item]) == {}
    item = commit()
    item["author"]["login"] = "human"
    assert merge.updated_dependencies([item]) == {}
    assert merge.updated_dependencies([]) == {}


def test_only_pinned_action_replacements_are_accepted() -> None:
    assert merge.action_pins([changed_file()]) == {"actions/setup-python": NEW_SHA}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("filename", "scripts/ci.sh"),
        ("status", "added"),
        ("patch", None),
        ("patch", "-permissions: read-all\n+permissions: write-all"),
        ("additions", 2),
    ],
)
def test_other_changes_and_truncated_patches_are_manual(field: str, value: object) -> None:
    file = changed_file()
    file[field] = value
    assert merge.action_pins([file]) == {}


def test_action_changes_cannot_add_steps_or_swap_repositories() -> None:
    file = changed_file()
    file["patch"] = file["patch"].replace("+      - uses: actions/", "+      - uses: attacker/")
    assert merge.action_pins([file]) == {}
    file = changed_file()
    file["patch"] = file["patch"].replace(NEW_SHA, "v7")
    assert merge.action_pins([file]) == {}


def test_complete_successful_checks_are_required() -> None:
    assert merge.checks_blocker(checks(), NEW_SHA) == ""
    assert merge.checks_blocker(checks()[1:], NEW_SHA)
    assert merge.checks_blocker([], NEW_SHA)


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "neutral", "skipped", None])
def test_required_checks_cannot_be_skipped_or_failed(conclusion: str | None) -> None:
    runs = checks()
    runs[0]["conclusion"] = conclusion
    assert merge.checks_blocker(runs, NEW_SHA)


def test_pending_spoofed_stale_and_newer_failed_checks_block() -> None:
    for field, value in [
        ("status", "in_progress"),
        ("app", {"slug": "other-app"}),
        ("head_sha", OLD_SHA),
    ]:
        runs = checks()
        runs[0][field] = value
        assert merge.checks_blocker(runs, NEW_SHA)
    runs = checks()
    newer = deepcopy(runs[0])
    newer.update(id=1000, conclusion="failure")
    assert merge.checks_blocker([newer, *runs], NEW_SHA)


def test_extra_failed_checks_block_but_known_optional_skips_do_not() -> None:
    extra = {**checks()[0], "id": 1000, "name": "extra", "conclusion": "failure"}
    assert merge.checks_blocker([*checks(), extra], NEW_SHA)
    for name in ("Build Docker image", "Trivy"):
        optional = {**extra, "name": name, "conclusion": "skipped"}
        assert merge.checks_blocker([*checks(), optional], NEW_SHA) == ""


def test_release_cooldown_is_exactly_three_days() -> None:
    assert merge.release_old_enough((NOW - timedelta(days=3)).isoformat(), NOW)
    assert not merge.release_old_enough((NOW - timedelta(days=3, seconds=-1)).isoformat(), NOW)
    assert not merge.release_old_enough((NOW + timedelta(days=1)).isoformat(), NOW)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict:
    data = {
        "pr": candidate(),
        "fresh": candidate(),
        "commits": [commit()],
        "signature": {"isValid": True, "wasSignedByGitHub": True},
        "files": [changed_file()],
        "alerts": [],
        "checks": checks(),
        "statuses": [],
        "reviews": [],
        "reviewDecision": None,
        "threads": [],
        "more_threads": False,
        "comparison": {"behind_by": 0, "base_commit": {"sha": OLD_SHA}},
        "release": {
            "publishedAt": (NOW - timedelta(days=3)).isoformat(),
            "isDraft": False,
            "isPrerelease": False,
            "tagCommit": {"oid": NEW_SHA},
        },
        "merge_result": {"merged": True, "sha": "c" * 40},
        "merge_calls": [],
    }
    calls = 0

    def rest(*, token: str, method: str, path: str, body: dict | None = None) -> dict:
        nonlocal calls
        assert token == "token"
        if method == "PUT":
            data["merge_calls"].append(body)
            return data["merge_result"]
        if path.endswith("/pulls/1"):
            calls += 1
            return data["pr" if calls == 1 else "fresh"]
        if "/compare/" in path:
            return data["comparison"]
        if "/check-runs?" in path:
            return {"total_count": len(data["checks"]), "check_runs": data["checks"]}
        if "/releases/tags/" in path:
            return data["release"]
        raise AssertionError(path)

    def paginate(token: str, path: str) -> list:
        assert token == "token"
        resource = "alerts" if "/dependabot/alerts?" in path else path.rsplit("/", 1)[1]
        return data[resource]

    def graphql(**kwargs: object) -> dict:
        if "object(oid:" in str(kwargs["query"]):
            return {"data": {"repository": {"object": {"signature": data["signature"]}}}}
        if "release(tagName:" in str(kwargs["query"]):
            return {"data": {"repository": {"release": data["release"]}}}
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewDecision": data["reviewDecision"],
                        "reviewThreads": {
                            "nodes": data["threads"],
                            "pageInfo": {"hasNextPage": data["more_threads"]},
                        },
                    }
                }
            }
        }

    monkeypatch.setattr(merge, "_github_rest", rest)
    monkeypatch.setattr(merge, "_fetch_paginated", paginate)
    monkeypatch.setattr(merge, "_github_graphql", graphql)
    return data


def test_dry_run_never_merges(github: dict) -> None:
    assert merge.process_pr("token", "owner/repo", 1, apply=False, now=NOW).startswith("DRY_RUN:")
    assert github["merge_calls"] == []


def test_apply_merges_only_the_verified_sha(github: dict) -> None:
    assert merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW).startswith("MERGED:")
    assert github["merge_calls"] == [{"sha": NEW_SHA, "merge_method": "squash"}]


def test_verified_human_signed_amendment_cannot_supply_metadata(github: dict) -> None:
    github["signature"] = {"isValid": True, "wasSignedByGitHub": False}
    assert "sign" in merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW).lower()
    assert github["merge_calls"] == []


@pytest.mark.parametrize("signature", [None, {"isValid": False, "wasSignedByGitHub": True}])
def test_missing_or_invalid_github_signature_blocks_merge(github: dict, signature: object) -> None:
    github["signature"] = signature
    assert "sign" in merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW).lower()
    assert github["merge_calls"] == []


@pytest.mark.parametrize("has_alert", [True, False])
def test_repository_security_alert_blocks_grouped_subaction_updates(github: dict, has_alert: bool) -> None:
    github["commits"][0]["commit"]["message"] = (
        MESSAGE.replace("actions/setup-python", "github/codeql-action/init")
        .replace("7.1.0", "4.39.1")
        .replace(
            "...\n",
            "- dependency-name: github/codeql-action/upload-sarif\n"
            "  dependency-version: 4.39.1\n"
            "  update-type: version-update:semver-patch\n...\n",
        )
    )
    file = github["files"][0]
    file["patch"] = file["patch"].replace("actions/setup-python", "github/codeql-action/init")
    file["patch"] += (
        f"\n-      - uses: github/codeql-action/upload-sarif@{OLD_SHA}"
        f"\n+      - uses: github/codeql-action/upload-sarif@{NEW_SHA}"
    )
    file["additions"] = file["deletions"] = 2
    github["alerts"] = [{"dependency": {"package": {"name": "github/codeql-action"}}}] if has_alert else []
    result = merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    if has_alert:
        assert "security alert" in result
        assert github["merge_calls"] == []
    else:
        assert result.startswith("MERGED:")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("alerts", [{"dependency": {"package": {"name": "actions/setup-python"}}}]),
        ("commits", []),
        ("files", []),
        ("checks", []),
        ("statuses", [{"id": 1, "context": "external", "state": "pending"}]),
        ("reviewDecision", "CHANGES_REQUESTED"),
        ("reviewDecision", "REVIEW_REQUIRED"),
        ("reviews", [{"user": {"login": "owner"}, "state": "CHANGES_REQUESTED"}]),
        ("threads", [{"isResolved": False}]),
        ("more_threads", True),
        ("comparison", {"behind_by": 1, "base_commit": {"sha": OLD_SHA}}),
        ("release", {"publishedAt": NOW.isoformat(), "isDraft": False, "isPrerelease": False}),
        ("release", {"publishedAt": NOW.isoformat(), "isDraft": False, "isPrerelease": True}),
    ],
)
def test_apply_fails_closed_at_each_gate(github: dict, key: str, value: object) -> None:
    github[key] = value
    result = merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    assert not result.startswith(("MERGED:", "DRY_RUN:"))
    assert github["merge_calls"] == []


def test_missing_release_is_a_manual_blocker_not_a_queue_failure(github: dict) -> None:
    github["release"] = None
    assert "no published release" in merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    assert github["merge_calls"] == []


def test_release_tag_must_match_the_pin(github: dict) -> None:
    github["release"]["tagCommit"]["oid"] = OLD_SHA
    assert "does not match" in merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    assert github["merge_calls"] == []


def test_release_api_permission_errors_remain_explicit(github: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    graphql = merge._github_graphql

    def forbidden_release(*, token: str, query: str, variables: dict) -> dict:
        if "release(tagName:" in query:
            raise RuntimeError("GraphQL forbidden")
        return graphql(token=token, query=query, variables=variables)

    monkeypatch.setattr(merge, "_github_graphql", forbidden_release)
    with pytest.raises(RuntimeError, match="GraphQL forbidden"):
        merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    assert github["merge_calls"] == []


def test_head_or_base_changes_during_verification_block_merge(github: dict) -> None:
    github["fresh"]["head"]["sha"] = OLD_SHA
    assert "changed" in merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    assert github["merge_calls"] == []


def test_main_changes_during_verification_block_merge(github: dict) -> None:
    github["fresh"]["base"]["sha"] = "c" * 40
    assert "changed" in merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    assert github["merge_calls"] == []


def test_new_security_hold_during_verification_blocks_merge(github: dict) -> None:
    github["fresh"]["labels"] = [{"name": "hold"}]
    assert "changed" in merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)
    assert github["merge_calls"] == []


def test_merge_refusal_is_an_explicit_failure(github: dict) -> None:
    github["merge_result"] = {"merged": False, "message": "Branch protection blocked merge"}
    with pytest.raises(RuntimeError, match="Branch protection"):
        merge.process_pr("token", "owner/repo", 1, apply=True, now=NOW)


def test_check_run_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    total = len(checks()) + 1
    rest = Mock(
        side_effect=[
            {"check_runs": checks(), "total_count": total},
            {"check_runs": [checks()[0]], "total_count": total},
        ]
    )
    monkeypatch.setattr(merge, "_github_rest", rest)
    assert merge.fetch_checks("token", "owner/repo", NEW_SHA) == [*checks(), checks()[0]]
    assert rest.call_count == 2
    assert "page=2" in rest.call_args.kwargs["path"]


def test_main_reports_candidates_and_stops_after_merge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr("sys.argv", ["dependabot_automerge", "--apply"])
    monkeypatch.setattr(merge, "_fetch_paginated", lambda *_: [candidate(), candidate()])
    process = Mock(return_value="MERGED: sha")
    monkeypatch.setattr(merge, "process_pr", process)
    merge.main()
    assert process.call_count == 1
    assert "#1: MERGED:" in capsys.readouterr().out


def test_main_continues_after_an_ineligible_release(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr("sys.argv", ["dependabot_automerge", "--apply"])
    monkeypatch.setattr(merge, "_fetch_paginated", lambda *_: [candidate(), candidate()])
    process = Mock(side_effect=["no published release: actions/example", "MERGED: sha"])
    monkeypatch.setattr(merge, "process_pr", process)
    merge.main()
    assert process.call_count == 2
    assert "no published release" in capsys.readouterr().out


def test_workflow_uses_only_trusted_default_branch_code() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/dependabot-automerge.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch", "workflow_run", "schedule"}
    assert triggers["workflow_run"]["types"] == ["completed"]
    steps = workflow["jobs"]["merge"]["steps"]
    assert steps[0]["with"]["ref"] == "main"
    assert steps[0]["with"]["persist-credentials"] is False
    assert workflow["permissions"] == {"contents": "read"}
    assert "github.ref == 'refs/heads/main'" in workflow["jobs"]["merge"]["if"]
    run = next(step for step in steps if "run" in step)
    assert "AUTOPILOT_USER_TOKEN" in run["env"]["GITHUB_TOKEN"]
    assert "--apply" in run["run"]
    config = yaml.safe_load((root / ".github/dependabot.yml").read_text())
    cooldowns = {entry["package-ecosystem"]: entry["cooldown"]["default-days"] for entry in config["updates"]}
    assert cooldowns == {"github-actions": 3, "pip": 7, "docker": 7, "terraform": 7}


def test_owner_approved_cooldown_exception_is_actions_only() -> None:
    config = (Path(__file__).resolve().parents[1] / ".github/dependabot.yml").read_text()
    rule = "package_managers.dependabot.dependabot-missing-cooldown.dependabot-missing-cooldown"
    assert config.count(f"nosemgrep: {rule}") == 1
    actions = config.split('package-ecosystem: "github-actions"', 1)[1].split('package-ecosystem: "docker"', 1)[0]
    assert f"default-days: 3  # nosemgrep: {rule}" in actions

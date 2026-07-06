from __future__ import annotations

from datetime import UTC, datetime

from scripts.pr_watchdog import (
    PRSummary,
    ReviewThread,
    body_links_issue,
    close_stale_pr,
    fetch_issue_acceptance,
    is_stale_closeable,
    linked_issue_number,
    maybe_nudge_agent,
    pr_age_days,
    ralph_nudge_history,
    ralph_signature,
    render_comment,
    render_nudge_comment,
    should_auto_promote,
    should_nudge_agent,
    unmet_dod_items,
)


def test_render_comment_marks_blocked_when_failing_checks_present() -> None:
    summary = PRSummary(
        number=1,
        url="https://example.invalid/pr/1",
        title="Example",
        failing_checks=("CI/Test",),
        pending_checks=(),
        unresolved_threads=(),
    )
    body = render_comment(summary)
    assert "Status: BLOCKED" in body
    assert "CI/Test" in body


def test_render_comment_marks_needs_opinion_when_unresolved_threads_present() -> None:
    summary = PRSummary(
        number=2,
        url="https://example.invalid/pr/2",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(
            ReviewThread(
                author="copilot-pull-request-reviewer",
                path="treesight/security/quota.py",
                url="https://example.invalid/thread/1",
                body="Needs fix",
            ),
        ),
    )
    body = render_comment(summary)
    assert "Needs Opinion" in body
    assert "Yes." in body
    assert "Status: BLOCKED" in body


def test_render_comment_marks_ready_when_no_blockers_or_pending() -> None:
    summary = PRSummary(
        number=3,
        url="https://example.invalid/pr/3",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
    )
    body = render_comment(summary)
    assert "Status: READY_FOR_MAINTAINER_REVIEW" in body


def test_render_comment_blocks_when_linked_issue_missing() -> None:
    summary = PRSummary(
        number=4,
        url="https://example.invalid/pr/4",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        missing_linked_issue=True,
    )
    body = render_comment(summary)
    assert "Linked issue: MISSING" in body
    assert "Closes #NNN" in body
    assert "Status: BLOCKED" in body


def test_render_comment_shows_linked_issue_present_by_default() -> None:
    summary = PRSummary(
        number=5,
        url="https://example.invalid/pr/5",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
    )
    body = render_comment(summary)
    assert "Linked issue: present" in body


def test_render_comment_flags_draft_ready_to_promote() -> None:
    summary = PRSummary(
        number=6,
        url="https://example.invalid/pr/6",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=True,
    )
    body = render_comment(summary)
    assert "Status: READY_TO_PROMOTE" in body
    assert "gh pr ready" in body


def test_draft_with_blockers_stays_blocked() -> None:
    summary = PRSummary(
        number=7,
        url="https://example.invalid/pr/7",
        title="Example",
        failing_checks=("CI/Test",),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=True,
    )
    body = render_comment(summary)
    assert "Status: BLOCKED" in body


def test_body_links_issue_detects_closing_keywords() -> None:
    assert body_links_issue("Closes #809")
    assert body_links_issue("This fixes #12 nicely")
    assert body_links_issue("resolves owner/repo#3")
    assert body_links_issue("FIXED #44")


def test_body_links_issue_rejects_bare_references() -> None:
    assert not body_links_issue("See #809 for context")
    assert not body_links_issue("Related to #12")
    assert not body_links_issue("")
    assert not body_links_issue("closes the gap (no number)")


def test_should_auto_promote_trusted_draft_ready_returns_true() -> None:
    summary = PRSummary(
        number=10,
        url="https://example.invalid/pr/10",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=True,
    )
    assert should_auto_promote(summary, "Copilot") is True


def test_should_auto_promote_untrusted_author_returns_false() -> None:
    summary = PRSummary(
        number=11,
        url="https://example.invalid/pr/11",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=True,
    )
    assert should_auto_promote(summary, "random-user") is False


def test_should_auto_promote_draft_with_blockers_returns_false() -> None:
    summary = PRSummary(
        number=12,
        url="https://example.invalid/pr/12",
        title="Example",
        failing_checks=("CI/Test",),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=True,
    )
    assert should_auto_promote(summary, "Copilot") is False


def test_should_auto_promote_draft_with_pending_checks_returns_false() -> None:
    summary = PRSummary(
        number=13,
        url="https://example.invalid/pr/13",
        title="Example",
        failing_checks=(),
        pending_checks=("CI/Test",),
        unresolved_threads=(),
        is_draft=True,
    )
    assert should_auto_promote(summary, "Copilot") is False


def test_should_auto_promote_non_draft_returns_false() -> None:
    summary = PRSummary(
        number=14,
        url="https://example.invalid/pr/14",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=False,
    )
    assert should_auto_promote(summary, "Copilot") is False


def test_should_auto_promote_missing_linked_issue_returns_false() -> None:
    summary = PRSummary(
        number=15,
        url="https://example.invalid/pr/15",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        missing_linked_issue=True,
        is_draft=True,
    )
    assert should_auto_promote(summary, "Copilot") is False


def _blocked_draft(number: int = 20) -> PRSummary:
    return PRSummary(
        number=number,
        url=f"https://example.invalid/pr/{number}",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        missing_linked_issue=True,
        is_draft=True,
    )


def test_pr_age_days_computes_days_since_updated() -> None:
    now = datetime(2026, 7, 6, tzinfo=UTC)
    pr = {"updated_at": "2026-07-01T00:00:00Z"}
    assert pr_age_days(pr, now=now) == 5.0


def test_pr_age_days_missing_updated_returns_zero() -> None:
    assert pr_age_days({}, now=datetime(2026, 7, 6, tzinfo=UTC)) == 0.0


def test_linked_issue_number_extracts_number() -> None:
    assert linked_issue_number("Closes #1040") == 1040
    assert linked_issue_number("fixes owner/repo#7") == 7


def test_linked_issue_number_returns_none_without_closing_ref() -> None:
    assert linked_issue_number("See #1040 for context") is None
    assert linked_issue_number("") is None


def test_is_stale_closeable_true_for_blocked_stale_draft() -> None:
    assert is_stale_closeable(_blocked_draft(), age_days=6.0, threshold_days=5.0) is True


def test_is_stale_closeable_false_when_fresh() -> None:
    assert is_stale_closeable(_blocked_draft(), age_days=2.0, threshold_days=5.0) is False


def test_is_stale_closeable_false_for_clean_draft() -> None:
    clean = PRSummary(
        number=21,
        url="https://example.invalid/pr/21",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=True,
    )
    assert is_stale_closeable(clean, age_days=10.0, threshold_days=5.0) is False


def test_is_stale_closeable_false_for_ready_non_draft() -> None:
    ready_blocked = PRSummary(
        number=22,
        url="https://example.invalid/pr/22",
        title="Example",
        failing_checks=("CI/Test",),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=False,
    )
    assert is_stale_closeable(ready_blocked, age_days=10.0, threshold_days=5.0) is False


def test_close_stale_pr_comments_closes_and_requeues(monkeypatch) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def fake_rest(*, token: str, method: str, path: str, body=None):
        calls.append((method, path, body))
        return None

    monkeypatch.setattr("scripts.pr_watchdog._github_rest", fake_rest)

    close_stale_pr(
        token="t",
        owner="o",
        repo="r",
        pr_number=1017,
        issue_number=1040,
        age_days=6.0,
        threshold_days=5.0,
    )

    # PR comment, PR close (PATCH), then issue re-queue comment.
    assert (calls[0][0], calls[0][1]) == ("POST", "/repos/o/r/issues/1017/comments")
    assert (calls[1][0], calls[1][1]) == ("PATCH", "/repos/o/r/pulls/1017")
    assert calls[1][2] == {"state": "closed"}
    assert (calls[2][0], calls[2][1]) == ("POST", "/repos/o/r/issues/1040/comments")


def test_close_stale_pr_skips_requeue_when_no_linked_issue(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "scripts.pr_watchdog._github_rest",
        lambda *, token, method, path, body=None: calls.append(path),
    )

    close_stale_pr(
        token="t",
        owner="o",
        repo="r",
        pr_number=1018,
        issue_number=None,
        age_days=9.0,
        threshold_days=5.0,
    )

    # Only the PR comment + PR close; no issue comment path.
    assert calls == ["/repos/o/r/issues/1018/comments", "/repos/o/r/pulls/1018"]


# ── Ralph loop (completion nudge) ────────────────────────────────────────────


def _agent_blocked(number: int = 30, *, missing_issue: bool = True) -> PRSummary:
    return PRSummary(
        number=number,
        url=f"https://example.invalid/pr/{number}",
        title="Example",
        failing_checks=("CI/Test",),
        pending_checks=(),
        unresolved_threads=(),
        missing_linked_issue=missing_issue,
        is_draft=False,
    )


def test_unmet_dod_items_lists_missing_issue_and_failing_checks() -> None:
    items = unmet_dod_items(_agent_blocked())
    joined = "\n".join(items)
    assert "Closes #NNN" in joined
    assert "CI/Test" in joined


def test_unmet_dod_items_draft_with_no_other_blockers_asks_to_mark_ready() -> None:
    draft = PRSummary(
        number=31,
        url="https://example.invalid/pr/31",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
        is_draft=True,
    )
    assert unmet_dod_items(draft) == ("Mark the PR ready for review once complete.",)


def test_ralph_signature_is_order_independent() -> None:
    assert ralph_signature(("b", "a")) == ralph_signature(("a", "b"))


def test_should_nudge_agent_true_for_blocked_agent_under_cap() -> None:
    assert should_nudge_agent(_agent_blocked(), "Copilot", attempts=0, max_attempts=3) is True


def test_should_nudge_agent_false_over_cap() -> None:
    assert should_nudge_agent(_agent_blocked(), "Copilot", attempts=3, max_attempts=3) is False


def test_should_nudge_agent_false_for_non_agent_author() -> None:
    result = should_nudge_agent(_agent_blocked(), "Hardcoreprawn", attempts=0, max_attempts=3)
    assert result is False


def test_should_nudge_agent_false_without_blockers() -> None:
    clean = PRSummary(
        number=32,
        url="https://example.invalid/pr/32",
        title="Example",
        failing_checks=(),
        pending_checks=(),
        unresolved_threads=(),
    )
    assert should_nudge_agent(clean, "Copilot", attempts=0, max_attempts=3) is False


def test_ralph_nudge_history_counts_and_returns_last_signature(monkeypatch) -> None:
    comments = [
        {"body": "unrelated"},
        {"body": "<!-- pr-watchdog-ralph -->\n<!-- ralph-sig: a|b -->\nnudge 1"},
        {"body": "<!-- pr-watchdog-ralph -->\n<!-- ralph-sig: c -->\nnudge 2"},
    ]
    monkeypatch.setattr("scripts.pr_watchdog._fetch_paginated", lambda token, path: comments)
    count, last_sig = ralph_nudge_history(token="t", owner="o", repo="r", pr_number=30)
    assert count == 2
    assert last_sig == "c"


def test_fetch_issue_acceptance_extracts_section(monkeypatch) -> None:
    issue_body = "## Problem\n\nx\n\n## Acceptance\n\n- must do A\n- must do B\n\n## Notes\n\ny"
    monkeypatch.setattr(
        "scripts.pr_watchdog._github_rest",
        lambda *, token, method, path, body=None: {"body": issue_body},
    )
    section = fetch_issue_acceptance(token="t", owner="o", repo="r", issue_number=99)
    assert section.startswith("## Acceptance")
    assert "must do A" in section
    assert "## Notes" not in section


def test_render_nudge_comment_mentions_copilot_and_items() -> None:
    rendered = render_nudge_comment(
        items=("Fix the failing check: CI/Test",),
        acceptance="## Acceptance\n\n- do X",
        attempt=1,
        max_attempts=3,
    )
    assert "@copilot" in rendered
    assert "<!-- pr-watchdog-ralph -->" in rendered
    assert "attempt 1/3" in rendered
    assert "CI/Test" in rendered


def test_maybe_nudge_agent_dry_run_reports_without_posting(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.pr_watchdog.ralph_nudge_history",
        lambda *, token, owner, repo, pr_number: (0, None),
    )
    posted: list[str] = []
    monkeypatch.setattr(
        "scripts.pr_watchdog._github_rest",
        lambda *, token, method, path, body=None: posted.append(path),
    )
    fired = maybe_nudge_agent(
        read_token="r",
        post_token="p",
        owner="o",
        repo="r",
        summary=_agent_blocked(),
        pr_body="Closes #40",
        author_login="Copilot",
        max_attempts=3,
        dry_run=True,
    )
    assert fired is True
    assert posted == []  # dry-run must not post


def test_maybe_nudge_agent_skips_when_unchanged(monkeypatch) -> None:
    summary = _agent_blocked()
    same_sig = ralph_signature(unmet_dod_items(summary))
    monkeypatch.setattr(
        "scripts.pr_watchdog.ralph_nudge_history",
        lambda *, token, owner, repo, pr_number: (1, same_sig),
    )
    posted: list[str] = []
    monkeypatch.setattr(
        "scripts.pr_watchdog._github_rest",
        lambda *, token, method, path, body=None: posted.append(path),
    )
    fired = maybe_nudge_agent(
        read_token="r",
        post_token="p",
        owner="o",
        repo="r",
        summary=summary,
        pr_body="Closes #40",
        author_login="Copilot",
        max_attempts=3,
        dry_run=False,
    )
    assert fired is False
    assert posted == []  # unchanged state → no re-nudge


def test_maybe_nudge_agent_posts_with_post_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.pr_watchdog.ralph_nudge_history",
        lambda *, token, owner, repo, pr_number: (0, None),
    )
    monkeypatch.setattr(
        "scripts.pr_watchdog.fetch_issue_acceptance",
        lambda *, token, owner, repo, issue_number: "## Acceptance\n\n- do X",
    )
    calls: list[tuple[str, str, str]] = []

    def fake_rest(*, token, method, path, body=None):
        calls.append((token, method, path))
        return None

    monkeypatch.setattr("scripts.pr_watchdog._github_rest", fake_rest)

    fired = maybe_nudge_agent(
        read_token="read",
        post_token="PAT",
        owner="o",
        repo="r",
        summary=_agent_blocked(number=30),
        pr_body="Closes #40",
        author_login="Copilot",
        max_attempts=3,
        dry_run=False,
    )
    assert fired is True
    # The nudge comment must be posted with the PAT (post_token), not the read token.
    assert calls == [("PAT", "POST", "/repos/o/r/issues/30/comments")]

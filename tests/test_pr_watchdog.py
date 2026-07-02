from __future__ import annotations

from scripts.pr_watchdog import (
    PRSummary,
    ReviewThread,
    body_links_issue,
    render_comment,
    should_auto_promote,
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

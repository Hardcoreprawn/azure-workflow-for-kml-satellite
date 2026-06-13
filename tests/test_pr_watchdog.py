from __future__ import annotations

from scripts.pr_watchdog import PRSummary, ReviewThread, render_comment


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

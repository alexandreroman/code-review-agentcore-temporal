from agentcore_review_shared.contract import Finding, PullRequestState
from agentcore_review_worker.lifecycle import dismiss
from agentcore_review_worker.markers import reply_marker
from agentcore_review_worker.models import DiscussionReply, FileChange, ReviewContent, ThreadComment
from agentcore_review_worker.publishing import (
    MAX_BODY_CHARS,
    MAX_INLINE_COMMENTS,
    bot_answers,
    budget_reply,
    build_review,
    check_output,
    closing_comment,
    comment_body,
    failed_reply,
    idle_close_comment,
    idle_warning_comment,
    no_longer_open_reply,
    not_open_fix_comment,
    off_thread_fix_reply,
    reply_body,
    split_changes,
    unavailable_check_output,
)

MARKER = "<!-- round:pr-o-r-1:1 -->"


def finding(finding_id, line=11, end_line=None, severity="high", suggestion=None) -> Finding:
    return Finding(
        id=finding_id,
        category="security",
        severity=severity,
        path="app/search.py",
        line=line,
        end_line=end_line,
        title="SQL injection",
        explanation="The name reaches SQL unescaped.",
        suggestion=suggestion,
    )


def content(findings, **extra) -> ReviewContent:
    return ReviewContent(round=1, summary_markdown="Summary.", findings=findings, **extra)


def test_comment_body_carries_the_marker_and_the_suggestion():
    body = comment_body(finding("F-007", suggestion="Bind parameters."))
    assert body.startswith("<!-- finding:F-007 -->")
    assert "high" in body and "Bind parameters." in body


def test_findings_on_diff_lines_go_inline_and_the_rest_into_the_body():
    commentable = {"app/search.py": {10, 11, 12}}
    findings = [finding("F-001", line=11), finding("F-002", line=50), finding("F-003", line=11, end_line=13)]
    payload = build_review(content(findings), commentable, MARKER, inline=True)
    assert [(c.path, c.line, c.side) for c in payload.comments] == [("app/search.py", 11, "RIGHT")]
    assert "<!-- finding:F-002 -->" in payload.body and "<!-- finding:F-003 -->" in payload.body
    assert payload.body.startswith(MARKER) and "Summary." in payload.body


def test_multi_line_findings_use_start_line():
    commentable = {"app/search.py": {10, 11, 12}}
    payload = build_review(content([finding("F-001", line=10, end_line=12)]), commentable, MARKER, inline=True)
    comment = payload.comments[0]
    assert (comment.start_line, comment.line, comment.start_side) == (10, 12, "RIGHT")


def test_inline_comments_are_capped():
    findings = [finding(f"F-{i:03d}") for i in range(1, 26)]
    payload = build_review(content(findings), {"app/search.py": {11}}, MARKER, inline=True)
    assert len(payload.comments) == MAX_INLINE_COMMENTS
    assert payload.body.count("<!-- finding:") == 25 - MAX_INLINE_COMMENTS


def test_without_inline_comments_every_finding_is_in_the_body():
    payload = build_review(content([finding("F-001"), finding("F-002")]), {"app/search.py": {11}}, MARKER, inline=False)
    assert payload.comments == []
    assert payload.body.count("<!-- finding:") == 2
    assert "### Findings" in payload.body and "### Other findings" not in payload.body


def test_body_reports_resolved_open_excluded_unlisted_and_unavailable():
    extra = {
        "resolved_ids": ["F-001"],
        "still_open": [finding("F-002")],
        "excluded": ["uv.lock"],
        "unlisted": 12,
        "unavailable": ["security"],
    }
    body = build_review(content([], **extra), {}, MARKER, inline=True).body
    for expected in ("F-001", "F-002", "uv.lock", "12 more files", "security"):
        assert expected in body


def test_body_reports_unlisted_files_without_excluded_ones():
    body = build_review(content([], unlisted=1), {}, MARKER, inline=True).body
    assert "### Not reviewed\n\n- 1 more file that GitHub does not list: too many changes" in body


def test_body_is_truncated_below_the_github_limit():
    body = build_review(
        ReviewContent(round=1, summary_markdown="x" * 70_000, findings=[]), {}, MARKER, inline=True
    ).body
    assert len(body) <= MAX_BODY_CHARS + 20
    assert body.endswith("(truncated)")


def test_check_output_counts_blocking_findings():
    _, title, summary = check_output([finding("F-002", severity="low"), finding("F-001", severity="critical")], [], 0)
    assert title == "2 open findings, 1 blocking"
    assert summary.index("F-001") < summary.index("F-002")
    assert check_output([], [], 0)[1] == "No open finding"


def test_check_is_red_only_for_blocking_findings():
    assert check_output([], [], 0)[0] == "success"
    assert check_output([finding("F-1", severity="medium"), finding("F-2", severity="low")], [], 0)[0] == "success"
    assert check_output([finding("F-1", severity="low"), finding("F-2", severity="high")], [], 0)[0] == "failure"
    assert check_output([finding("F-1", severity="critical")], [], 0)[0] == "failure"


def test_check_output_names_the_unavailable_reviewers():
    _, title, summary = check_output([finding("F-001", severity="low")], ["security", "performance (batch 2)"], 0)
    assert title == "1 open finding, 0 blocking, 2 reviewers unavailable"
    assert "Not reviewed in this round (reviewer unavailable): security, performance (batch 2)." in summary
    _, title, summary = check_output([], ["maintainability"], 0)
    assert title == "No open finding, 1 reviewer unavailable"
    assert "maintainability" in summary


def test_check_output_counts_the_unlisted_files():
    conclusion, title, summary = check_output([], [], 42)
    assert conclusion == "success" and title == "No open finding, 42 files not listed"
    assert "Not reviewed in this round (not listed by GitHub, too many changes): 42 files." in summary


def test_dismissing_the_last_blocking_finding_turns_the_check_green():
    state = PullRequestState(open_findings=[finding("F-001"), finding("F-002", severity="low")])
    assert check_output(state.open_findings, [], 0)[0] == "failure"
    dismiss(state, "F-001", "not reachable", "alice")
    conclusion, title, _ = check_output(state.open_findings, [], 0)
    assert conclusion == "success" and title == "1 open finding, 0 blocking"


def test_unavailable_check_output_lists_every_reviewer():
    title, summary = unavailable_check_output(3, ["security", "performance", "maintainability"])
    assert title == "Review unavailable"
    assert summary == (
        "No reviewer completed round 3 (unavailable: security, performance, maintainability), "
        "so this head was not reviewed. Push a commit to retry."
    )


def test_closing_comment_calls_out_a_bypass():
    findings = [finding("F-004", severity="medium"), finding("F-001", severity="high")]
    text = closing_comment("admin", findings, "<!-- m -->")
    assert (
        text == "⚠️ Merged by @admin bypassing AI Review, 2 open findings: F-001 (high), F-004 (medium).\n\n<!-- m -->"
    )


def test_closing_comment_without_blocking_findings():
    text = closing_comment(None, [finding("F-002", severity="low")], "<!-- m -->")
    assert text == "Merged with 1 open finding: F-002 (low).\n\n<!-- m -->"


def test_the_idle_warning_announces_the_time_left_before_the_close():
    text = idle_warning_comment(600, 900, "<!-- m -->")
    assert text == (
        "No activity for 10 minutes: this pull request will be closed in 5 minutes. "
        "Push a commit to keep it open.\n\n<!-- m -->"
    )


def test_idle_durations_that_are_not_whole_minutes_read_in_seconds():
    text = idle_warning_comment(90, 150, "<!-- m -->")
    assert text.startswith("No activity for 90 seconds: this pull request will be closed in 1 minute.")


def test_the_idle_close_comment_gives_the_idle_duration():
    assert idle_close_comment(900, "<!-- m -->") == (
        "Closed after 15 minutes without activity. Reopen it for a new review.\n\n<!-- m -->"
    )


def test_a_fix_refused_in_a_thread_points_to_both_ways_of_fixing():
    text = off_thread_fix_reply("F-001", ["F-001", "F-003"], "<!-- m -->")
    assert text == (
        "This thread is about F-001: `/fix F-001 F-003` was not applied. Comment `/fix` here to fix F-001, "
        "or `/fix F-001 F-003` in the conversation.\n\n<!-- m -->"
    )


def test_a_fix_refused_in_the_conversation_lists_the_open_findings_most_severe_first():
    open_findings = [finding("F-010", severity="low"), finding("F-009", severity="high")]
    text = not_open_fix_comment(["F-099"], open_findings, "<!-- m -->")
    assert text == "F-099 is not an open finding: nothing was fixed. Open findings: F-009, F-010.\n\n<!-- m -->"


def test_a_fix_refused_with_no_open_finding():
    text = not_open_fix_comment(["F-001", "F-002"], [], "<!-- m -->")
    assert text == "F-001, F-002 are not open findings: nothing was fixed. No finding is open.\n\n<!-- m -->"


def test_a_thread_reply_starts_with_the_verdict_and_ends_with_its_marker():
    keep = reply_body(
        "F-004", DiscussionReply(verdict="keep", answer=" The query is still built by hand. "), "<!-- m -->"
    )
    assert keep == "**F-004 stays open.** The query is still built by hand.\n\n<!-- m -->"
    dismissed = reply_body("F-004", DiscussionReply(verdict="dismiss", answer="Right."), "<!-- m -->")
    assert dismissed.startswith("**F-004 dismissed.** Right.")


def test_only_the_agents_answers_count_toward_the_budget():
    marker = reply_marker("pr-o-r-3", 777)
    answer = reply_body("F-001", DiscussionReply(verdict="keep", answer="Still unsafe."), marker)
    thread = [
        ThreadComment(id=1, author="bot[bot]", body=comment_body(finding("F-001"))),
        ThreadComment(id=2, author="alice", body="why?"),
        ThreadComment(id=3, author="bot[bot]", body=answer),
        ThreadComment(id=4, author="bot[bot]", body=failed_reply(marker)),
        ThreadComment(id=5, author="bot[bot]", body=budget_reply(marker)),
        ThreadComment(id=6, author="bot[bot]", body=no_longer_open_reply("F-001", marker)),
        ThreadComment(id=7, author="alice", body=answer),
    ]
    assert bot_answers(thread, "bot[bot]") == 1
    assert bot_answers([], "bot[bot]") == 0


def test_split_changes_rejects_protected_and_escaping_paths():
    paths = [
        "app/a.py",
        "./app/b.py",
        ".github/workflows/ci.yml",
        ".GitHub/x",
        "../etc/passwd",
        "/abs.py",
        "",
        "app/a.py",
    ]
    accepted, rejected = split_changes([FileChange(path=p, new_content=f"{i}") for i, p in enumerate(paths)])
    assert [(c.path, c.new_content) for c in accepted] == [("app/a.py", "7"), ("app/b.py", "1")]
    assert rejected == [".github/workflows/ci.yml", ".GitHub/x", "../etc/passwd", "/abs.py", ""]

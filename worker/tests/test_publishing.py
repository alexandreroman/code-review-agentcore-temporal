from agentcore_review_shared.contract import Finding
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
    body = comment_body(finding("S-07", suggestion="Bind parameters."))
    assert body.startswith("<!-- finding:S-07 -->")
    assert "high" in body and "Bind parameters." in body


def test_findings_on_diff_lines_go_inline_and_the_rest_into_the_body():
    commentable = {"app/search.py": {10, 11, 12}}
    findings = [finding("S-01", line=11), finding("S-02", line=50), finding("S-03", line=11, end_line=13)]
    payload = build_review(content(findings), commentable, MARKER, inline=True)
    assert [(c.path, c.line, c.side) for c in payload.comments] == [("app/search.py", 11, "RIGHT")]
    assert "<!-- finding:S-02 -->" in payload.body and "<!-- finding:S-03 -->" in payload.body
    assert payload.body.startswith(MARKER) and "Summary." in payload.body


def test_multi_line_findings_use_start_line():
    commentable = {"app/search.py": {10, 11, 12}}
    payload = build_review(content([finding("S-01", line=10, end_line=12)]), commentable, MARKER, inline=True)
    comment = payload.comments[0]
    assert (comment.start_line, comment.line, comment.start_side) == (10, 12, "RIGHT")


def test_inline_comments_are_capped():
    findings = [finding(f"S-{i:02d}") for i in range(1, 26)]
    payload = build_review(content(findings), {"app/search.py": {11}}, MARKER, inline=True)
    assert len(payload.comments) == MAX_INLINE_COMMENTS
    assert payload.body.count("<!-- finding:") == 25 - MAX_INLINE_COMMENTS


def test_without_inline_comments_every_finding_is_in_the_body():
    payload = build_review(content([finding("S-01"), finding("S-02")]), {"app/search.py": {11}}, MARKER, inline=False)
    assert payload.comments == []
    assert payload.body.count("<!-- finding:") == 2
    assert "### Findings" in payload.body and "### Other findings" not in payload.body


def test_body_reports_resolved_open_excluded_unlisted_and_unavailable():
    extra = {
        "resolved_ids": ["S-01"],
        "still_open": [finding("S-02")],
        "excluded": ["uv.lock"],
        "unlisted": 12,
        "unavailable": ["security"],
    }
    body = build_review(content([], **extra), {}, MARKER, inline=True).body
    for expected in ("S-01", "S-02", "uv.lock", "12 more files", "security"):
        assert expected in body


def test_body_reports_unlisted_files_without_excluded_ones():
    body = build_review(content([], unlisted=1), {}, MARKER, inline=True).body
    assert "### Not reviewed\n\n- 1 more file that GitHub does not list: too many changes" in body


def test_body_says_the_merge_is_blocked_by_critical_or_high_findings():
    extra = {"still_open": [finding("S-03", severity="critical"), finding("M-01", severity="low")]}
    findings = [finding("P-01", severity="high"), finding("S-02", severity="medium")]
    body = build_review(content(findings, **extra), {}, MARKER, inline=True).body
    assert body.startswith(
        f"{MARKER}\n\n## AI Review — round 1\n\n**Merge blocked** by 2 critical or high findings: S-03, P-01.\n\n"
        "Summary."
    )


def test_body_says_the_merge_is_blocked_by_a_single_critical_or_high_finding():
    body = build_review(content([finding("S-03", severity="critical")]), {}, MARKER, inline=True).body
    assert "## AI Review — round 1\n\n**Merge blocked** by 1 critical or high finding: S-03.\n\nSummary." in body


def test_a_blocking_finding_still_open_from_an_earlier_round_blocks_the_merge():
    body = build_review(content([], still_open=[finding("S-01", severity="high")]), {}, MARKER, inline=True).body
    assert "**Merge blocked** by 1 critical or high finding: S-01." in body


def test_body_says_the_pull_request_is_mergeable_without_critical_or_high_findings():
    extra = {"still_open": [finding("S-02", severity="low")]}
    body = build_review(content([finding("S-01", severity="medium")], **extra), {}, MARKER, inline=True).body
    assert "## AI Review — round 1\n\n**Mergeable**: no critical or high finding is open.\n\nSummary." in body


def test_body_is_truncated_below_the_github_limit():
    body = build_review(
        ReviewContent(round=1, summary_markdown="x" * 70_000, findings=[]), {}, MARKER, inline=True
    ).body
    assert len(body) <= MAX_BODY_CHARS + 20
    assert body.endswith("(truncated)")


def test_check_title_counts_the_blocking_findings_and_the_total():
    _, title, summary = check_output([finding("S-02", severity="low"), finding("S-01", severity="critical")])
    assert title == "Merge blocked: 1 critical or high finding open (2 in total)"
    assert summary.index("S-01") < summary.index("S-02")
    _, title, _ = check_output([finding("S-01", severity="critical"), finding("P-01", severity="high")])
    assert title == "Merge blocked: 2 critical or high findings open"


def test_check_title_without_blocking_findings():
    assert check_output([finding("S-01", severity="medium")])[1] == "1 open finding, none critical or high"
    _, title, summary = check_output([finding("S-01", severity="medium"), finding("S-02", severity="low")])
    assert title == "2 open findings, none critical or high"
    assert "Merge blocked" not in summary
    assert check_output([]) == ("success", "No open finding", "No finding is open.")


def test_check_summary_starts_with_the_blocking_findings_and_the_way_out():
    findings = [finding("M-01", severity="low"), finding("P-01", severity="high"), finding("S-01", severity="critical")]
    _, _, summary = check_output(findings)
    assert summary.startswith(
        "**Merge blocked** by 2 critical or high findings: S-01 (critical), P-01 (high). "
        "Fix them (push a commit or comment `/fix`) or have them dismissed in their thread. "
        "The check turns green once none is left.\n\n- **S-01** critical"
    )
    assert summary.index("P-01 (high)") < summary.index("- **M-01**")


def test_check_summary_for_a_single_blocking_finding():
    _, _, summary = check_output([finding("S-01", severity="critical"), finding("M-01", severity="medium")])
    assert summary.startswith(
        "**Merge blocked** by 1 critical or high finding: S-01 (critical). "
        "Fix it (push a commit or comment `/fix`) or have it dismissed in its thread. "
        "The check turns green once none is left.\n\n"
    )


def test_check_is_red_only_for_blocking_findings():
    assert check_output([finding("S-01", severity="medium"), finding("S-02", severity="low")])[0] == "success"
    assert check_output([finding("S-01", severity="low"), finding("S-02", severity="high")])[0] == "failure"
    assert check_output([finding("S-01", severity="critical")])[0] == "failure"


def test_check_output_names_the_unavailable_reviewers():
    _, title, summary = check_output(
        [finding("S-01", severity="low")], unavailable=["security", "performance (batch 2)"]
    )
    assert title == "1 open finding, none critical or high, 2 reviewers unavailable"
    assert "Not reviewed in this round (reviewer unavailable): security, performance (batch 2)." in summary
    _, title, summary = check_output([], unavailable=["maintainability"])
    assert title == "No open finding, 1 reviewer unavailable"
    assert "maintainability" in summary
    _, title, _ = check_output([finding("S-01", severity="high")], unavailable=["security"], unlisted=3)
    assert title == "Merge blocked: 1 critical or high finding open, 1 reviewer unavailable, 3 files not listed"


def test_check_output_counts_the_unlisted_files():
    conclusion, title, summary = check_output([], unlisted=42)
    assert conclusion == "success" and title == "No open finding, 42 files not listed"
    assert "Not reviewed in this round (not listed by GitHub, too many changes): 42 files." in summary


def test_unavailable_check_output_lists_every_reviewer():
    conclusion, title, summary = unavailable_check_output(3, ["security", "performance", "maintainability"])
    assert conclusion == "failure" and title == "Review unavailable"
    assert summary == (
        "No reviewer completed round 3 (unavailable: security, performance, maintainability), "
        "so this head was not reviewed. Push a commit to retry."
    )


def test_closing_comment_calls_out_a_bypass():
    findings = [finding("S-04", severity="medium"), finding("S-01", severity="high")]
    text = closing_comment("admin", findings, "<!-- m -->")
    assert text == "⚠️ Merged by @admin bypassing AI Review, 2 open findings: S-01 (high), S-04 (medium).\n\n<!-- m -->"


def test_closing_comment_without_blocking_findings():
    text = closing_comment(None, [finding("S-02", severity="low")], "<!-- m -->")
    assert text == "Merged with 1 open finding: S-02 (low).\n\n<!-- m -->"


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
    text = off_thread_fix_reply("S-01", ["S-01", "S-03"], "<!-- m -->")
    assert text == (
        "This thread is about S-01: `/fix S-01 S-03` was not applied. Comment `/fix` here to fix S-01, "
        "or `/fix S-01 S-03` in the conversation.\n\n<!-- m -->"
    )


def test_a_fix_refused_in_the_conversation_lists_the_open_findings_most_severe_first():
    open_findings = [finding("S-10", severity="low"), finding("S-09", severity="high")]
    text = not_open_fix_comment(["S-99"], open_findings, "<!-- m -->")
    assert text == "S-99 is not an open finding: nothing was fixed. Open findings: S-09, S-10.\n\n<!-- m -->"


def test_a_fix_refused_with_no_open_finding():
    text = not_open_fix_comment(["S-01", "S-02"], [], "<!-- m -->")
    assert text == "S-01, S-02 are not open findings: nothing was fixed. No finding is open.\n\n<!-- m -->"


def test_a_thread_reply_starts_with_the_verdict_and_ends_with_its_marker():
    keep = reply_body(
        "S-04", DiscussionReply(verdict="keep", answer=" The query is still built by hand. "), "<!-- m -->"
    )
    assert keep == "**S-04 stays open.** The query is still built by hand.\n\n<!-- m -->"
    dismissed = reply_body("S-04", DiscussionReply(verdict="dismiss", answer="Right."), "<!-- m -->")
    assert dismissed.startswith("**S-04 dismissed.** Right.")


def test_only_the_agents_answers_count_toward_the_budget():
    marker = reply_marker("pr-o-r-3", 777)
    answer = reply_body("S-01", DiscussionReply(verdict="keep", answer="Still unsafe."), marker)
    thread = [
        ThreadComment(id=1, author="bot[bot]", body=comment_body(finding("S-01"))),
        ThreadComment(id=2, author="alice", body="why?"),
        ThreadComment(id=3, author="bot[bot]", body=answer),
        ThreadComment(id=4, author="bot[bot]", body=failed_reply(marker)),
        ThreadComment(id=5, author="bot[bot]", body=budget_reply(marker)),
        ThreadComment(id=6, author="bot[bot]", body=no_longer_open_reply("S-01", marker)),
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

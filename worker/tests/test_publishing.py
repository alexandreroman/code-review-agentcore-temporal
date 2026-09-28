import pytest
from agentcore_review_worker.markers import reply_marker
from agentcore_review_worker.models import (
    CheckOutput,
    DiscussionReply,
    FileChange,
    Finding,
    ReviewContent,
    ThreadComment,
)
from agentcore_review_worker.publishing import (
    MAX_BODY_CHARS,
    MAX_INLINE_COMMENTS,
    bot_answers,
    budget_reply,
    build_review,
    check_output,
    closing_comment,
    comment_body,
    failed_fix_comment,
    failed_reply,
    idle_close_comment,
    idle_warning_comment,
    no_longer_open_reply,
    not_open_fix_comment,
    off_thread_fix_reply,
    reopen_comment,
    reply_body,
    split_changes,
    unavailable_check_output,
)

MARKER = "<!-- round:pr-o-r-1:1 -->"
PATH = "src/main/java/com/example/orders/OrderRepository.java"


def finding(finding_id, line=11, end_line=None, severity="high", suggestion=None) -> Finding:
    return Finding(
        id=finding_id,
        category="security",
        severity=severity,
        path=PATH,
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
    commentable = {PATH: {10, 11, 12}}
    findings = [finding("S-01", line=11), finding("S-02", line=50), finding("S-03", line=11, end_line=13)]
    payload = build_review(content(findings), commentable, MARKER, inline=True)
    assert [(c.path, c.line, c.side) for c in payload.comments] == [(PATH, 11, "RIGHT")]
    assert "<!-- finding:S-02 -->" in payload.body and "<!-- finding:S-03 -->" in payload.body
    assert payload.body.startswith(MARKER) and "Summary." in payload.body


def test_multi_line_findings_use_start_line():
    commentable = {PATH: {10, 11, 12}}
    payload = build_review(content([finding("S-01", line=10, end_line=12)]), commentable, MARKER, inline=True)
    comment = payload.comments[0]
    assert (comment.start_line, comment.line, comment.start_side) == (10, 12, "RIGHT")


def test_inline_comments_are_capped():
    findings = [finding(f"S-{i:02d}") for i in range(1, 26)]
    payload = build_review(content(findings), {PATH: {11}}, MARKER, inline=True)
    assert len(payload.comments) == MAX_INLINE_COMMENTS
    assert payload.body.count("<!-- finding:") == 25 - MAX_INLINE_COMMENTS


def test_without_inline_comments_every_finding_is_in_the_body():
    payload = build_review(content([finding("S-01"), finding("S-02")]), {PATH: {11}}, MARKER, inline=False)
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


def test_the_merge_status_of_new_and_still_open_findings_follows_the_heading():
    extra = {"still_open": [finding("S-03", severity="critical"), finding("M-01", severity="low")]}
    findings = [finding("P-01", severity="high"), finding("S-02", severity="medium")]
    body = build_review(content(findings, **extra), {}, MARKER, inline=True).body
    assert body.startswith(
        f"{MARKER}\n\n## AI Review — round 1\n\n**Merge blocked** by 2 critical or high findings: S-03, P-01.\n\n"
        "Summary."
    )


def test_body_is_truncated_below_the_github_limit():
    body = build_review(
        ReviewContent(round=1, summary_markdown="x" * 70_000, findings=[]), {}, MARKER, inline=True
    ).body
    assert len(body) <= MAX_BODY_CHARS + 20
    assert body.endswith("(truncated)")


def test_a_blocking_finding_turns_the_check_red_and_counts_in_its_title():
    output = check_output([finding("S-02", severity="low"), finding("S-01", severity="critical")])
    assert output.conclusion == "failure"
    assert output.title == "Merge blocked: 1 critical or high finding open (2 in total)"
    assert output.summary.index("S-01") < output.summary.index("S-02")
    assert "Fix it" in output.summary
    output = check_output([finding("S-01", severity="critical"), finding("P-01", severity="high")])
    assert output.conclusion == "failure" and output.title == "Merge blocked: 2 critical or high findings open"


def test_without_blocking_findings_the_check_is_green():
    output = check_output([finding("S-01", severity="medium")])
    assert output.conclusion == "success" and output.title == "1 open finding, none critical or high"
    output = check_output([finding("S-01", severity="medium"), finding("S-02", severity="low")])
    assert output.conclusion == "success" and output.title == "2 open findings, none critical or high"
    assert "Merge blocked" not in output.summary
    assert check_output([]) == CheckOutput(conclusion="success", title="No open finding", summary="No finding is open.")


def test_check_summary_starts_with_the_blocking_findings_and_the_way_out():
    findings = [finding("M-01", severity="low"), finding("P-01", severity="high"), finding("S-01", severity="critical")]
    summary = check_output(findings).summary
    assert summary.startswith(
        "**Merge blocked** by 2 critical or high findings: S-01 (critical), P-01 (high). "
        "Fix them (push a commit or comment `/fix`) or have them dismissed in their thread. "
        "The check turns green once none is left.\n\n- **S-01** critical"
    )
    assert summary.index("P-01 (high)") < summary.index("- **M-01**")


def test_check_output_names_the_unavailable_reviewers():
    output = check_output([finding("S-01", severity="low")], unavailable=["security", "performance (batch 2)"])
    assert output.title == "1 open finding, none critical or high, 2 reviewers unavailable"
    assert "Not reviewed in this round (reviewer unavailable): security, performance (batch 2)." in output.summary
    output = check_output([], unavailable=["maintainability"])
    assert output.title == "No open finding, 1 reviewer unavailable"
    assert "maintainability" in output.summary
    output = check_output([finding("S-01", severity="high")], unavailable=["security"], unlisted=3)
    assert output.title == "Merge blocked: 1 critical or high finding open, 1 reviewer unavailable, 3 files not listed"


def test_check_output_counts_the_unlisted_files():
    output = check_output([], unlisted=42)
    assert output.conclusion == "success" and output.title == "No open finding, 42 files not listed"
    assert "Not reviewed in this round (not listed by GitHub, too many changes): 42 files." in output.summary


def test_unavailable_check_output_lists_every_reviewer():
    output = unavailable_check_output(3, ["security", "performance", "maintainability"])
    assert output.conclusion == "failure" and output.title == "Review unavailable"
    assert output.summary == (
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


def test_the_reopen_comment_announces_the_next_round_after_the_earlier_threads():
    assert reopen_comment(2, "<!-- m -->") == (
        "Reopened: a new review starts. The earlier finding threads still open are resolved first, then round 3 "
        "reviews the whole pull request; this takes a few minutes.\n\n<!-- m -->"
    )


def test_the_reopen_comment_without_an_earlier_round_only_announces_the_review():
    assert reopen_comment(0, "<!-- m -->") == "Reopened: a new review starts; it takes a few minutes.\n\n<!-- m -->"


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


@pytest.mark.parametrize(
    ("error_type", "text"),
    [
        ("BranchMoved", "Fix 2 abandoned: the branch changed while it was prepared. Comment `/fix` to try again."),
        ("ForkNotSupported", "Fix 2 not pushed: this pull request comes from a fork, which the bot cannot push to."),
        ("AgentUnavailable", "Fix 2 failed: nothing was pushed. Comment `/fix` to try again."),
        (None, "Fix 2 failed: nothing was pushed. Comment `/fix` to try again."),
    ],
)
def test_a_failed_fix_says_whether_a_new_fix_can_help(error_type, text):
    assert failed_fix_comment(2, error_type, "<!-- m -->") == f"{text}\n\n<!-- m -->"


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
        "src/A.java",
        "./src//B.java",
        ".github/workflows/ci.yml",
        ".GitHub/x",
        "../etc/passwd",
        "/Abs.java",
        "",
        "src/A.java",
    ]
    accepted, rejected = split_changes([FileChange(path=p, new_content=f"{i}") for i, p in enumerate(paths)])
    assert [(c.path, c.new_content) for c in accepted] == [("src/A.java", "7"), ("src/B.java", "1")]
    assert rejected == [".github/workflows/ci.yml", ".GitHub/x", "../etc/passwd", "/Abs.java", ""]

import pytest
from agentcore_review_worker.lifecycle import merge_status
from agentcore_review_worker.markers import extract_finding_ids, reply_marker
from agentcore_review_worker.models import (
    CheckOutput,
    ConversationReply,
    DiscussionReply,
    Finding,
    ReviewContent,
    ThreadComment,
)
from agentcore_review_worker.publishing import (
    MAX_BODY_CHARS,
    MAX_INLINE_COMMENTS,
    NO_ANSWER_TEXT,
    OFF_TOPIC_TEXT,
    ConversationPost,
    bot_answers,
    budget_reply,
    build_review,
    check_output,
    closing_comment,
    comment_body,
    conversation_post,
    failed_fix_comment,
    failed_reply,
    idle_close_comment,
    idle_warning_comment,
    no_longer_open_reply,
    not_open_fix_comment,
    off_thread_fix_reply,
    reopen_comment,
    reply_body,
    unavailable_check_output,
)

MARKER = "<!-- round:pr-o-r-1:1 -->"
PATH = "src/main/java/com/example/orders/OrderRepository.java"


def finding(finding_id, line=11, end_line=None, severity="high", suggestion=None, explanation=None) -> Finding:
    return Finding(
        id=finding_id,
        category="security",
        severity=severity,
        path=PATH,
        line=line,
        end_line=end_line,
        title="SQL injection",
        explanation=explanation or "The name reaches SQL unescaped.",
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
    body = build_review(content([], unlisted=1), {}, MARKER, inline=True).body
    assert "### Not reviewed\n\n- 1 more file that GitHub does not list" in body


def test_the_merge_status_of_new_and_still_open_findings_follows_the_heading():
    extra = {"still_open": [finding("S-03", severity="critical"), finding("M-01", severity="low")]}
    findings = [finding("P-01", severity="high"), finding("S-02", severity="medium")]
    body = build_review(content(findings, **extra), {}, MARKER, inline=True).body
    assert body.startswith(
        f"{MARKER}\n\n## AI Review — round 1\n\n**Merge blocked** by 2 critical or high findings: S-03, P-01.\n\n"
        "Summary."
    )


def test_findings_beyond_the_body_limit_are_left_out_whole_and_counted():
    findings = [finding(f"S-{i:02d}", explanation="x" * 5_000) for i in range(1, 21)]
    body = build_review(content(findings), {}, MARKER, inline=False).body
    shown = extract_finding_ids(body)
    assert len(body) <= MAX_BODY_CHARS
    assert body.count("<!-- finding:") == len(shown)  # no marker is cut
    assert 0 < len(shown) < len(findings) and shown == [f.id for f in findings[: len(shown)]]
    assert f"{len(findings) - len(shown)} more findings not shown." in body


def test_a_single_finding_left_out_is_counted_in_the_singular():
    findings = [finding(f"S-{i:02d}", explanation="x" * 25_000) for i in range(1, 4)]
    body = build_review(content(findings), {}, MARKER, inline=False).body
    assert "1 more finding not shown." in body


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
    assert summary.startswith(f"{merge_status(findings)} Fix them (push a commit or comment `/fix`)")
    assert summary.index("- **S-01**") < summary.index("- **P-01**") < summary.index("- **M-01**")


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


def test_unavailable_check_output_fails_and_lists_every_reviewer():
    output = unavailable_check_output(3, ["security", "performance", "maintainability"])
    assert output.conclusion == "failure"
    assert "security, performance, maintainability" in output.summary


def test_closing_comment_calls_out_a_bypass():
    findings = [finding("S-04", severity="medium"), finding("S-01", severity="high")]
    text = closing_comment("admin", findings, "<!-- m -->")
    assert text == "⚠️ Merged by @admin bypassing AI Review, 2 open findings: S-01 (high), S-04 (medium).\n\n<!-- m -->"


def test_closing_comment_without_blocking_findings():
    text = closing_comment(None, [finding("S-02", severity="low")], "<!-- m -->")
    assert text == "Merged with 1 open finding: S-02 (low).\n\n<!-- m -->"


def test_the_idle_warning_announces_the_time_left_before_the_close():
    text = idle_warning_comment(600, 900, "<!-- m -->")
    assert "10 minutes" in text and "5 minutes" in text and text.endswith("<!-- m -->")


def test_idle_durations_that_are_not_whole_minutes_read_in_seconds():
    text = idle_warning_comment(90, 150, "<!-- m -->")
    assert "90 seconds" in text and "1 minute." in text


def test_the_idle_close_comment_gives_the_idle_duration():
    text = idle_close_comment(900, "<!-- m -->")
    assert "15 minutes" in text and text.endswith("<!-- m -->")


def test_the_reopen_comment_names_the_next_round_only_after_an_earlier_one():
    after_round_2 = reopen_comment(2, "<!-- m -->")
    assert "round 3" in after_round_2 and after_round_2.endswith("<!-- m -->")
    assert "round" not in reopen_comment(0, "<!-- m -->")


def test_a_fix_refused_in_a_thread_repeats_the_refused_command():
    text = off_thread_fix_reply("S-01", ["S-01", "S-03"], "<!-- m -->")
    assert "`/fix S-01 S-03`" in text and text.endswith("<!-- m -->")


def test_a_fix_refused_in_the_conversation_lists_the_open_findings_most_severe_first():
    open_findings = [finding("S-10", severity="low"), finding("S-09", severity="high")]
    text = not_open_fix_comment(["S-99"], open_findings, "<!-- m -->")
    assert text == "S-99 is not an open finding: nothing was fixed. Open findings: S-09, S-10.\n\n<!-- m -->"


def test_a_fix_refused_with_no_open_finding():
    text = not_open_fix_comment(["S-01", "S-02"], [], "<!-- m -->")
    assert text == "S-01, S-02 are not open findings: nothing was fixed. No finding is open.\n\n<!-- m -->"


@pytest.mark.parametrize(
    ("error_type", "invites_a_new_fix"),
    [
        ("BranchMoved", True),
        ("ForkNotSupported", False),
        ("EmptyFixPlan", False),
        ("AgentUnavailable", True),
        (None, True),
    ],
)
def test_a_failed_fix_says_whether_a_new_fix_can_help(error_type, invites_a_new_fix):
    text = failed_fix_comment(2, error_type, "<!-- m -->")
    assert ("/fix" in text) == invites_a_new_fix
    assert "Fix 2" in text and text.endswith("<!-- m -->")


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


ANSWER = ConversationReply(off_topic=False, respond=True, answer=" The query is built in `OrderRepository`. ")


@pytest.mark.parametrize("mentioned", [True, False])
def test_an_answer_is_posted_and_counted_with_or_without_a_mention(mentioned):
    post = conversation_post(ANSWER, mentioned, "<!-- m -->")
    assert post == ConversationPost("The query is built in `OrderRepository`.\n\n<!-- m -->", answered=True)


@pytest.mark.parametrize("answer", ["Sure, here is a poem.", ""])
def test_an_off_topic_mention_gets_the_fixed_text_never_the_model_answer(answer):
    reply = ConversationReply(off_topic=True, respond=True, answer=answer)
    assert conversation_post(reply, True, "<!-- m -->") == ConversationPost(
        f"{OFF_TOPIC_TEXT}\n\n<!-- m -->", answered=False
    )
    assert conversation_post(reply, False, "<!-- m -->") is None


@pytest.mark.parametrize(
    "reply",
    [
        ConversationReply(off_topic=False, respond=False, answer=""),
        ConversationReply(off_topic=False, respond=False, answer="An answer the agent chose not to give."),
        ConversationReply(off_topic=False, respond=True, answer="  \n "),
    ],
)
def test_no_answer_gets_the_fallback_on_a_mention_and_silence_otherwise(reply):
    assert conversation_post(reply, True, "<!-- m -->") == ConversationPost(
        f"{NO_ANSWER_TEXT}\n\n<!-- m -->", answered=False
    )
    assert conversation_post(reply, False, "<!-- m -->") is None

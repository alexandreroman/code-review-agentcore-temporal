from agentcore_review_shared.contract import FileChange, Finding
from agentcore_review_worker.models import ReviewContent
from agentcore_review_worker.publishing import (
    MAX_BODY_CHARS,
    MAX_INLINE_COMMENTS,
    build_review,
    check_output,
    closing_comment,
    comment_body,
    commit_message,
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
    payload = build_review(content(findings), commentable, MARKER)
    assert [(c.path, c.line, c.side) for c in payload.comments] == [("app/search.py", 11, "RIGHT")]
    assert "<!-- finding:F-002 -->" in payload.body and "<!-- finding:F-003 -->" in payload.body
    assert payload.body.startswith(MARKER) and "Summary." in payload.body


def test_multi_line_findings_use_start_line():
    payload = build_review(content([finding("F-001", line=10, end_line=12)]), {"app/search.py": {10, 11, 12}}, MARKER)
    comment = payload.comments[0]
    assert (comment.start_line, comment.line, comment.start_side) == (10, 12, "RIGHT")


def test_inline_comments_are_capped():
    findings = [finding(f"F-{i:03d}") for i in range(1, 26)]
    payload = build_review(content(findings), {"app/search.py": {11}}, MARKER)
    assert len(payload.comments) == MAX_INLINE_COMMENTS
    assert payload.body.count("<!-- finding:") == 25 - MAX_INLINE_COMMENTS


def test_without_inline_comments_every_finding_is_in_the_body():
    payload = build_review(content([finding("F-001"), finding("F-002")]), {"app/search.py": {11}}, MARKER, inline=False)
    assert payload.comments == []
    assert payload.body.count("<!-- finding:") == 2


def test_body_reports_resolved_open_excluded_and_unavailable():
    extra = {
        "resolved_ids": ["F-001"],
        "still_open": [finding("F-002")],
        "excluded": ["uv.lock"],
        "unavailable": ["security"],
    }
    body = build_review(content([], **extra), {}, MARKER).body
    for expected in ("No new finding in this round.", "F-001", "F-002", "uv.lock", "security"):
        assert expected in body


def test_body_is_truncated_below_the_github_limit():
    body = build_review(ReviewContent(round=1, summary_markdown="x" * 70_000, findings=[]), {}, MARKER).body
    assert len(body) <= MAX_BODY_CHARS + 20
    assert body.endswith("(truncated)")


def test_check_output_counts_blocking_findings():
    title, summary = check_output([finding("F-002", severity="low"), finding("F-001", severity="critical")])
    assert title == "2 open findings, 1 blocking"
    assert summary.index("F-001") < summary.index("F-002")
    assert check_output([])[0] == "No open finding"


def test_check_output_names_the_unavailable_reviewers():
    title, summary = check_output([finding("F-001", severity="low")], ["security", "performance (batch 2)"])
    assert title == "1 open finding, 0 blocking, 2 reviewers unavailable"
    assert "Not reviewed in this round (reviewer unavailable): security, performance (batch 2)." in summary
    title, summary = check_output([], ["maintainability"])
    assert title == "No open finding, 1 reviewer unavailable"
    assert "maintainability" in summary


def test_unavailable_check_output_lists_every_reviewer():
    title, summary = unavailable_check_output(3, ["security", "performance", "maintainability"])
    assert title == "Review unavailable"
    assert summary == (
        "No reviewer completed round 3 (unavailable: security, performance, maintainability), "
        "so this head was not reviewed. Push a commit to retry."
    )


def test_closing_comment_calls_out_a_bypass():
    text = closing_comment("admin", [finding("F-004", severity="medium"), finding("F-001", severity="high")])
    assert text == "⚠️ Merged by @admin bypassing AI Review, 2 open findings: F-001 (high), F-004 (medium)."


def test_closing_comment_without_blocking_findings():
    assert closing_comment(None, [finding("F-002", severity="low")]) == "Merged with 1 open finding: F-002 (low)."


def test_commit_message_ends_with_the_trailer():
    trailer = "Review-Fix: pr-o-r-1/1"
    assert commit_message("Fix SQL injection\n\n- F-001\n", trailer) == f"Fix SQL injection\n\n- F-001\n\n{trailer}"


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

import pytest
from agentcore_review_shared.contract import (
    Category,
    Finding,
    FindingDraft,
    FixRequested,
    PullRequestState,
)
from agentcore_review_worker.lifecycle import (
    MAX_FIX_DELIVERIES,
    apply_summary,
    clean_report,
    fallback_summary,
    memo,
    next_action,
    number_findings,
    record_fix_request,
    record_head,
    resolved_ids,
)
from agentcore_review_worker.models import ReviewerReport, ReviewSummary, SynthesisInput


def draft(category="security", severity="high", path="app/search.py", line=5, title="SQL injection") -> FindingDraft:
    return FindingDraft(category=category, severity=severity, path=path, line=line, title=title, explanation="why")


def finding(finding_id: str, **overrides) -> Finding:
    return Finding(**draft(**overrides).model_dump(), id=finding_id)


def test_close_wins_then_review_then_fix():
    state = PullRequestState(pending_head_sha="b", pending_fix=FixRequested(requested_by="dev", delivery_id="d"))
    assert next_action(state, closed=True) == "close"
    assert next_action(state, closed=False) == "review"
    state.pending_head_sha = None
    assert next_action(state, closed=False) == "fix"
    state.pending_fix = None
    assert next_action(state, closed=False) is None


def test_a_pending_head_equal_to_the_reviewed_one_is_no_review():
    assert next_action(PullRequestState(last_reviewed_sha="a", pending_head_sha="a"), closed=False) is None


@pytest.mark.parametrize("head", ["a", "b", "c"])
def test_duplicate_reviewed_or_in_review_heads_are_ignored(head):
    state = PullRequestState(last_reviewed_sha="a", pending_head_sha="b")
    assert record_head(state, head, reviewing_sha="c") is False
    assert state.pending_head_sha == "b"


def test_a_new_head_becomes_the_pending_review():
    state = PullRequestState(last_reviewed_sha="a")
    assert record_head(state, "d") is True
    assert state.pending_head_sha == "d"


def test_a_fix_request_becomes_pending_once_per_delivery():
    state = PullRequestState()
    first = FixRequested(requested_by="alice", delivery_id="d1")
    assert record_fix_request(state, first) is True
    state.pending_fix = None  # the fix ran
    assert record_fix_request(state, FixRequested(requested_by="alice", delivery_id="d1")) is False
    assert state.pending_fix is None
    assert record_fix_request(state, FixRequested(requested_by="bob", delivery_id="d2")) is True
    assert state.pending_fix.requested_by == "bob"


def test_seen_fix_deliveries_keep_only_the_most_recent():
    state = PullRequestState()
    for number in range(MAX_FIX_DELIVERIES + 5):
        record_fix_request(state, FixRequested(requested_by="alice", delivery_id=f"d{number}"))
    assert len(state.fix_deliveries) == MAX_FIX_DELIVERIES
    assert state.fix_deliveries[0] == "d5"
    assert state.fix_deliveries[-1] == f"d{MAX_FIX_DELIVERIES + 4}"


def test_clean_report_pins_the_category_and_keeps_known_open_ids():
    report = ReviewerReport(findings=[draft(category="performance")], resolved_ids=["f-001", "F-009", " F-002 "])
    cleaned = clean_report(report, Category.SECURITY, ["F-001", "F-002"])
    assert [f.category for f in cleaned.findings] == [Category.SECURITY]
    assert cleaned.resolved_ids == ["F-001", "F-002"]


def test_number_findings_follows_the_report_order():
    reports = [
        ReviewerReport(findings=[draft(line=1), draft(line=2)]),
        ReviewerReport(findings=[draft(category="performance", line=3)]),
    ]
    findings, next_number = number_findings(reports, 4)
    assert [f.id for f in findings] == ["F-004", "F-005", "F-006"]
    assert [f.line for f in findings] == [1, 2, 3]
    assert next_number == 7


def test_resolved_ids_are_merged_and_sorted():
    reports = [ReviewerReport(resolved_ids=["F-003"]), ReviewerReport(resolved_ids=["F-001", "F-003"])]
    assert resolved_ids(reports) == ["F-001", "F-003"]


def test_apply_summary_drops_duplicates_and_follows_the_order():
    new = [finding("F-001", severity="low"), finding("F-002"), finding("F-003", severity="medium")]
    summary = ReviewSummary(summary_markdown="s", ordered_ids=["F-002", "F-404", "F-002"], duplicates=["F-003"])
    assert [f.id for f in apply_summary(new, summary)] == ["F-002", "F-001"]


def test_apply_summary_never_drops_every_finding():
    new = [finding("F-001"), finding("F-002")]
    summary = ReviewSummary(summary_markdown="s", ordered_ids=[], duplicates=["F-001", "F-002"])
    assert [f.id for f in apply_summary(new, summary)] == ["F-001", "F-002"]


def test_fallback_summary_keeps_the_most_severe_finding_per_line():
    new = [finding("F-001", severity="medium"), finding("F-002", severity="critical"), finding("F-003", line=9)]
    summary = fallback_summary(SynthesisInput(new_findings=new, resolved_ids=["F-000"]))
    assert summary.ordered_ids == ["F-002", "F-003"]
    assert summary.duplicates == ["F-001"]
    assert "F-002 (critical)" in summary.summary_markdown
    assert "F-000" not in summary.summary_markdown  # the review body lists the resolved IDs


def test_fallback_summary_without_new_findings():
    assert fallback_summary(SynthesisInput(new_findings=[])).summary_markdown == "No new finding in this round."


def test_memo_lists_open_findings_most_severe_first():
    open_findings = [finding("F-001", severity="low"), finding("F-002", severity="critical")]
    state = PullRequestState(round=2, open_findings=open_findings)
    assert memo("waiting for changes", state) == {
        "state": "waiting for changes",
        "round": 2,
        "open_findings": ["F-002 critical app/search.py:5 SQL injection", "F-001 low app/search.py:5 SQL injection"],
    }

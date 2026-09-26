import pytest
from agentcore_review_shared.contract import (
    CHECK_NAME,
    PULL_REQUEST_WORKFLOW,
    QUERY_GET_FINDINGS,
    SIGNAL_FIX_REQUESTED,
    SIGNAL_PR_CLOSED,
    SIGNAL_PR_UPDATED,
    Category,
    Finding,
    FindingDraft,
    PrRef,
    PullRequestInput,
    PullRequestOutcome,
    ReviewerReport,
    Severity,
)
from pydantic import ValidationError


def draft(**overrides) -> FindingDraft:
    values = {
        "category": "security",
        "severity": "high",
        "path": "app/search.py",
        "line": 5,
        "title": "SQL injection",
        "explanation": "f-string in SQL",
    }
    values.update(overrides)
    return FindingDraft(**values)


def test_names_match_the_spec():
    assert (SIGNAL_PR_UPDATED, SIGNAL_FIX_REQUESTED, SIGNAL_PR_CLOSED) == ("pr_updated", "fix_requested", "pr_closed")
    assert QUERY_GET_FINDINGS == "get_findings"
    assert CHECK_NAME == "AI Review"
    assert PULL_REQUEST_WORKFLOW == "PullRequestWorkflow"


def test_severity_rank_and_blocking():
    assert [s.rank for s in Severity] == [0, 1, 2, 3]
    assert Severity.CRITICAL.blocking and Severity.HIGH.blocking
    assert not Severity.MEDIUM.blocking and not Severity.LOW.blocking


def test_finding_draft_parses_enums_and_rejects_line_zero():
    d = draft()
    assert d.category is Category.SECURITY and d.severity is Severity.HIGH
    with pytest.raises(ValidationError):
        draft(line=0)


def test_finding_extends_draft_with_id():
    f = Finding(**draft().model_dump(), id="F-001")
    assert f.id == "F-001" and f.comment_id is None


def test_reviewer_report_defaults_to_empty_lists():
    report = ReviewerReport()
    assert report.findings == [] and report.resolved_ids == []


def test_pull_request_input_round_trips_through_json():
    pr = PrRef(owner="o", repo="r", number=3, installation_id=42)
    original = PullRequestInput(pr=pr)
    restored = PullRequestInput.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.state.round == 0 and restored.state.next_finding_number == 1


def test_outcome_holds_open_findings():
    outcome = PullRequestOutcome(
        merged=True, closed_by="alex", open_findings=[Finding(**draft().model_dump(), id="F-1")], rounds=2
    )
    assert outcome.open_findings[0].id == "F-1"


@pytest.mark.parametrize(
    ("raw", "expected"), [("Security", Category.SECURITY), (" PERFORMANCE ", Category.PERFORMANCE)]
)
def test_categories_tolerate_case_and_spaces(raw, expected):
    assert draft(category=raw).category is expected


def test_severities_tolerate_case_in_nested_reports():
    report = ReviewerReport.model_validate({"findings": [draft().model_dump() | {"severity": "Critical"}]})
    assert report.findings[0].severity is Severity.CRITICAL


def test_unknown_enum_values_are_still_rejected():
    with pytest.raises(ValidationError):
        draft(category="style")

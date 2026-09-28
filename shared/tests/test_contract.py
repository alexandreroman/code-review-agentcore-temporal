import pytest
from agentcore_review_shared.contract import (
    AgentCoreSession,
    Category,
    FindingDraft,
    Severity,
    agentcore_identity,
    parse_agentcore_identity,
    pr_workflow_id,
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


def test_severity_rank_and_blocking():
    assert [s.rank for s in Severity] == [0, 1, 2, 3]
    assert Severity.CRITICAL.blocking and Severity.HIGH.blocking
    assert not Severity.MEDIUM.blocking and not Severity.LOW.blocking


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("category", "Security", Category.SECURITY),
        ("category", " PERFORMANCE ", Category.PERFORMANCE),
        ("severity", "Critical", Severity.CRITICAL),
        ("severity", " low ", Severity.LOW),
    ],
)
def test_enums_tolerate_case_and_spaces(field, raw, expected):
    finding = draft(**{field: raw})
    assert getattr(finding, field) is expected


def test_unknown_enum_values_are_still_rejected():
    with pytest.raises(ValidationError):
        draft(category="style")


def test_pr_workflow_id_ignores_case_differences_between_events():
    assert pr_workflow_id("OctoCat", "Agentcore-Review-Demo-App", 7) == pr_workflow_id(
        "octocat", "agentcore-review-demo-app", 7
    )


def test_agentcore_identity_round_trip():
    identity = agentcore_identity("b-1a2b3c", "bdc33ca1-7e55-4b64-a041-ac100aa2272c")
    assert identity == "agentcore:b-1a2b3c:bdc33ca1-7e55-4b64-a041-ac100aa2272c"
    assert parse_agentcore_identity(identity) == AgentCoreSession("b-1a2b3c", "bdc33ca1-7e55-4b64-a041-ac100aa2272c")


@pytest.mark.parametrize(
    "identity",
    ["dev:laptop", "agentcore:only-endpoint", "agentcore::session", "agentcore:endpoint:", "12345@host", ""],
)
def test_parse_rejects_non_agentcore_identities(identity):
    assert parse_agentcore_identity(identity) is None


def test_session_id_may_contain_colons():
    assert parse_agentcore_identity("agentcore:ep:a:b") == AgentCoreSession("ep", "a:b")

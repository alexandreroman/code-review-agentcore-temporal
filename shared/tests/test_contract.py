import pytest
from agentcore_review_shared.contract import (
    AgentCoreSession,
    Category,
    agentcore_identity,
    format_finding_id,
    parse_agentcore_identity,
    parse_finding_id,
    pr_workflow_id,
)


def test_finding_id_round_trip():
    assert format_finding_id(Category.SECURITY, 1) == "S-01"
    assert format_finding_id(Category.MAINTAINABILITY, 100) == "M-100"
    assert parse_finding_id("P-07") == (Category.PERFORMANCE, 7)


@pytest.mark.parametrize("text", ["F-003", "X-01", "s-01", "S-", "S-٣", " S-01"])
def test_parse_rejects_what_is_not_a_finding_id(text):
    assert parse_finding_id(text) is None


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


@pytest.mark.parametrize("raw", ["Security", " Security ", " SECURITY "])
def test_enums_tolerate_case_and_spaces(raw):
    assert Category(raw) is Category.SECURITY


def test_unknown_enum_values_are_still_rejected():
    with pytest.raises(ValueError):
        Category("style")

import pytest
from agentic_review_shared.identity import AgentCoreSession, agentcore_identity, dev_identity, parse_agentcore_identity


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


@pytest.mark.parametrize(("endpoint", "session"), [("", "s"), ("bad:name", "s"), ("ep", "")])
def test_agentcore_identity_rejects_invalid_parts(endpoint, session):
    with pytest.raises(ValueError):
        agentcore_identity(endpoint, session)


def test_dev_identity():
    assert dev_identity("donnager") == "dev:donnager"

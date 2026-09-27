import pytest
from agentcore_review_router.rules import (
    KillTally,
    can_run_commands,
    is_bot_login,
    kill_comment,
    kill_targets,
    stop_outcome,
)
from agentcore_review_shared.contract import AgentCoreSession


@pytest.mark.parametrize(
    ("permission", "allowed"),
    [
        ("admin", True),
        ("write", True),
        ("triage", False),
        ("read", False),
        ("none", False),
        ("", False),
        (None, False),
        ("Admin", False),
    ],
)
def test_only_write_access_runs_commands(permission, allowed):
    assert can_run_commands(permission) is allowed


@pytest.mark.parametrize(
    ("login", "expected"), [("tar-bot[bot]", True), ("octocat", False), (None, False), ("tar-bot", False)]
)
def test_only_the_bot_login_starts_a_finding_thread(login, expected):
    assert is_bot_login(login, "tar-bot[bot]") is expected


def test_kill_targets_keep_each_agentcore_session_once():
    identities = [
        "agentcore:b_2:s-9",
        "dev:laptop",
        "agentcore:b_1:s-1",
        "agentcore:b_2:s-9",
    ]
    assert kill_targets(identities) == [AgentCoreSession("b_1", "s-1"), AgentCoreSession("b_2", "s-9")]


def test_no_agentcore_poller_means_no_target():
    assert kill_targets(["dev:laptop"]) == []
    assert kill_targets([]) == []


@pytest.mark.parametrize(
    ("code", "outcome"),
    [
        (None, "stopped"),
        ("ResourceNotFoundException", "gone"),
        ("ConflictException", "retry"),
        ("ThrottlingException", "retry"),
        ("timeout", "retry"),
        ("AccessDeniedException", "failed"),
        ("ValidationException", "failed"),
    ],
)
def test_stop_outcome(code, outcome):
    assert stop_outcome(code) == outcome


def test_tally_counts_unconfirmed_stops_as_failed():
    tally = KillTally(stopped=1).add(["stopped", "gone", "retry", "failed"])
    assert tally == KillTally(stopped=2, gone=1, failed=2)


@pytest.mark.parametrize(
    ("tally", "text"),
    [
        (KillTally(stopped=1), "💥 1 AgentCore session stopped."),
        (KillTally(stopped=3), "💥 3 AgentCore sessions stopped."),
        (KillTally(stopped=2, gone=1), "💥 2 AgentCore sessions stopped, 1 already gone."),
        (KillTally(gone=2), "💥 0 AgentCore sessions stopped, 2 already gone."),
        (KillTally(stopped=1, failed=1), "💥 1 AgentCore session stopped, 1 failed (see the router logs)."),
    ],
)
def test_kill_comment(tally, text):
    assert kill_comment(tally) == text

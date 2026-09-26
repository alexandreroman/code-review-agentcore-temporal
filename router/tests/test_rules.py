import pytest
from agentcore_review_router.rules import (
    DEV_KILL_REPLY,
    NO_REVIEW_REPLY,
    NO_WORKER_REPLY,
    REACTION_DENIED,
    REACTION_FIX,
    REACTION_KILL,
    KillTally,
    can_run_commands,
    kill_comment,
    kill_scope,
    kill_targets,
    stop_outcome,
)
from agentcore_review_shared.identity import AgentCoreSession


@pytest.mark.parametrize(
    ("permission", "allowed"),
    [
        ("admin", True),
        ("maintain", True),
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
    ("queue", "scope"), [("review-dev", "dev"), ("review", "prod"), (None, "prod"), ("other", "prod")]
)
def test_kill_scope(queue, scope):
    assert kill_scope(queue, "review-dev") == scope


def test_kill_targets_keep_each_agentcore_session_once():
    identities = [
        "agentcore:b_2:s-9",
        "dev:laptop",
        "agentcore:b_1:s-1",
        "agentcore:b_2:s-9",
        "40213@ip-10-0-0-1",
        "agentcore::s-2",
        "agentcore:b_1:",
    ]
    assert kill_targets(identities) == [AgentCoreSession("b_1", "s-1"), AgentCoreSession("b_2", "s-9")]


def test_kill_targets_keep_colons_in_session_ids():
    assert kill_targets(["agentcore:b_1:a:b"]) == [AgentCoreSession("b_1", "a:b")]


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


def test_replies_and_reactions_match_the_spec():
    assert NO_REVIEW_REPLY == "No review in progress."
    assert DEV_KILL_REPLY == "Dev worker: Ctrl-C is your friend."
    assert NO_WORKER_REPLY == "No active worker, nothing to kill."
    assert (REACTION_DENIED, REACTION_FIX, REACTION_KILL) == ("confused", "eyes", "rocket")

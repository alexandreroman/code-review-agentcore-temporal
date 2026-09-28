import pytest
from agentcore_review_router.rules import (
    KillTally,
    can_run_commands,
    fix_finding_ids,
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
    ("arguments", "finding_ids"),
    [
        ((), []),
        (("F-001", "F-003"), ["F-001", "F-003"]),
        (("f-001", "F-001"), ["F-001"]),
        (("F-1000",), ["F-1000"]),
    ],
)
def test_fix_arguments_name_findings_uppercased_once_each(arguments, finding_ids):
    assert fix_finding_ids(arguments) == finding_ids


@pytest.mark.parametrize(
    "arguments",
    [("foo",), ("F-001", "please"), ("F-001,",), ("F-",), ("F001",), ("#F-001",), ("F-٣",)],
)
def test_fix_arguments_other_than_finding_ids_are_refused(arguments):
    assert fix_finding_ids(arguments) is None


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

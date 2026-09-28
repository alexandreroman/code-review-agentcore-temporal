import json
from pathlib import Path

import pytest
from agentcore_review_router.routing import (
    ForwardReply,
    Ignore,
    RouterConfig,
    RunCommand,
    SendSignal,
    StartOrSignal,
    load_payload,
    route,
)
from agentcore_review_shared.contract import SIGNAL_PR_CLOSED, PrClosed
from temporalio.common import WorkflowIDReusePolicy

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = RouterConfig(prod_queue="review", dev_queue="review-dev", dev_branch_prefix="dev/", app_slug="tar-bot")
WF = "pr-octocat-agentcore-review-demo-app-3"
# Each comment event is loaded from the fixture of the same name.
COMMENT_EVENTS = ["issue_comment", "pull_request_review_comment"]


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.mark.parametrize(
    ("action", "policy"),
    [
        ("opened", WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY),
        ("synchronize", WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY),
        ("reopened", WorkflowIDReusePolicy.ALLOW_DUPLICATE),
    ],
)
def test_pr_updates_start_or_signal(action, policy):
    payload = load("pull_request")
    payload["action"] = action
    result = route("pull_request", payload, "delivery-1", CONFIG)
    assert isinstance(result, StartOrSignal)
    assert result.workflow_id == WF and result.task_queue == "review" and result.reuse_policy == policy
    assert result.signal.head_sha == "a1b2c3d4e5f6" and result.signal.delivery_id == "delivery-1"
    assert (result.pr.owner, result.pr.repo, result.pr.number, result.pr.installation_id) == (
        "octocat",
        "agentcore-review-demo-app",
        3,
        90210,
    )


def test_dev_branch_goes_to_the_dev_queue():
    payload = load("pull_request")
    payload["pull_request"]["head"]["ref"] = "dev/customer-search"
    assert route("pull_request", payload, "d", CONFIG).task_queue == "review-dev"


def test_bot_synchronize_is_still_routed():
    payload = load("pull_request")
    payload["action"] = "synchronize"
    payload["sender"] = {"login": "tar-bot[bot]"}
    assert isinstance(route("pull_request", payload, "d", CONFIG), StartOrSignal)


def test_merged_close_signals_the_merger():
    payload = load("pull_request")
    payload["action"] = "closed"
    payload["pull_request"]["merged"] = True
    payload["pull_request"]["merged_by"] = {"login": "admin-user"}
    result = route("pull_request", payload, "d", CONFIG)
    assert isinstance(result, SendSignal) and result.workflow_id == WF and result.signal_name == SIGNAL_PR_CLOSED
    assert result.payload == PrClosed(merged=True, closed_by="admin-user", delivery_id="d")


def test_unmerged_close_by_the_reset_bot_is_routed():
    payload = load("pull_request")
    payload["action"] = "closed"
    payload["sender"] = {"login": "tar-bot[bot]"}
    result = route("pull_request", payload, "d", CONFIG)
    assert isinstance(result, SendSignal)
    assert result.payload == PrClosed(merged=False, closed_by="tar-bot[bot]", delivery_id="d")


@pytest.mark.parametrize("action", ["edited", "labeled", "ready_for_review", "assigned"])
def test_other_pr_actions_are_ignored(action):
    payload = load("pull_request")
    payload["action"] = action
    assert isinstance(route("pull_request", payload, "d", CONFIG), Ignore)


@pytest.mark.parametrize(
    ("body", "command"), [("/fix", "fix"), ("/kill", "kill"), ("/fix please", "fix"), ("  /kill\n", "kill")]
)
def test_commands(body, command):
    payload = load("issue_comment")
    payload["comment"]["body"] = body
    result = route("issue_comment", payload, "d", CONFIG)
    assert isinstance(result, RunCommand)
    assert (result.command, result.workflow_id, result.comment_id, result.comment_kind, result.author) == (
        command,
        WF,
        555,
        "issue",
        "octocat",
    )


@pytest.mark.parametrize(("body", "command"), [("/fix", "fix"), ("/kill", "kill")])
def test_commands_in_reply_to_a_review_comment(body, command):
    payload = load("pull_request_review_comment")
    payload["comment"]["body"] = body
    result = route("pull_request_review_comment", payload, "d", CONFIG)
    assert isinstance(result, RunCommand)
    assert (result.command, result.workflow_id, result.comment_id, result.comment_kind, result.author) == (
        command,
        WF,
        777,
        "review",
        "octocat",
    )
    assert result.pr.number == 3


def test_fix_in_a_review_thread_carries_the_thread_root():
    result = route("pull_request_review_comment", load("pull_request_review_comment"), "d", CONFIG)
    assert isinstance(result, RunCommand) and result.thread_root_id == 666


def test_fix_as_a_top_level_review_comment_fixes_everything():
    payload = load("pull_request_review_comment")
    del payload["comment"]["in_reply_to_id"]
    result = route("pull_request_review_comment", payload, "d", CONFIG)
    assert isinstance(result, RunCommand) and result.thread_root_id is None


def test_fix_in_the_conversation_fixes_everything():
    result = route("issue_comment", load("issue_comment"), "d", CONFIG)
    assert isinstance(result, RunCommand) and result.thread_root_id is None


@pytest.mark.parametrize("event", COMMENT_EVENTS)
@pytest.mark.parametrize(("body", "arguments"), [("/fix", ()), ("/fix  F-001\nF-003 ", ("F-001", "F-003"))])
def test_a_command_carries_the_words_after_it(event, body, arguments):
    payload = load(event)
    payload["comment"]["body"] = body
    result = route(event, payload, "d", CONFIG)
    assert isinstance(result, RunCommand) and result.arguments == arguments


@pytest.mark.parametrize("body", ["Why? The input is validated upstream.", "please /fix", "/FIX"])
def test_plain_replies_in_a_review_thread_are_forwarded(body):
    payload = load("pull_request_review_comment")
    payload["comment"]["body"] = body
    result = route("pull_request_review_comment", payload, "d", CONFIG)
    assert isinstance(result, ForwardReply)
    assert (result.workflow_id, result.comment_id, result.thread_root_id, result.author, result.delivery_id) == (
        WF,
        777,
        666,
        "octocat",
        "d",
    )
    assert result.bot_login == "tar-bot[bot]"
    assert result.pr.number == 3


@pytest.mark.parametrize("event", COMMENT_EVENTS)
@pytest.mark.parametrize("body", ["/fixit", "please /fix", "/FIX", "", "LGTM", "/review"])
def test_non_commands_outside_a_review_thread_are_ignored(event, body):
    payload = load(event)
    payload["comment"]["body"] = body
    payload["comment"].pop("in_reply_to_id", None)
    assert isinstance(route(event, payload, "d", CONFIG), Ignore)


@pytest.mark.parametrize("event", COMMENT_EVENTS)
@pytest.mark.parametrize("body", ["/fix", "Why?"])
def test_bot_comments_are_ignored_by_login(event, body):
    payload = load(event)
    payload["comment"]["body"] = body
    payload["sender"] = {"login": "tar-bot[bot]"}
    assert isinstance(route(event, payload, "d", CONFIG), Ignore)


def test_comments_on_plain_issues_are_ignored():
    payload = load("issue_comment")
    del payload["issue"]["pull_request"]
    assert isinstance(route("issue_comment", payload, "d", CONFIG), Ignore)


@pytest.mark.parametrize("event", COMMENT_EVENTS)
@pytest.mark.parametrize("action", ["edited", "deleted"])
def test_edited_or_deleted_comments_are_ignored(event, action):
    payload = load(event)
    payload["action"] = action
    assert isinstance(route(event, payload, "d", CONFIG), Ignore)


@pytest.mark.parametrize("event", ["ping", "installation", "push", "check_run"])
def test_other_events_are_ignored(event):
    assert isinstance(route(event, {}, "d", CONFIG), Ignore)


@pytest.mark.parametrize("body", [b"", b"not json", b"[1, 2]", b'"text"', b"null", b"\xff\xfe\x00"])
def test_bodies_that_are_not_json_objects_are_rejected(body):
    assert load_payload(body) is None


def test_json_object_body_is_loaded():
    assert load_payload(b'{"action": "opened"}') == {"action": "opened"}


@pytest.mark.parametrize("event", COMMENT_EVENTS)
def test_comment_without_body_is_ignored(event):
    payload = load(event)
    payload["comment"]["body"] = None
    assert isinstance(route(event, payload, "d", CONFIG), Ignore)

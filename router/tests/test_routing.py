import copy
import json
from pathlib import Path

import pytest
from agentcore_review_router.routing import (
    Ignore,
    RouterConfig,
    RunCommand,
    SendSignal,
    StartOrSignal,
    load_payload,
    route,
)
from agentcore_review_shared.contract import SIGNAL_PR_CLOSED, PrClosed

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = RouterConfig(
    prod_queue="review", dev_queue="review-dev", dev_branch_prefix="dev/", app_id=5078593, app_slug="tar-bot"
)
WF = "pr-octocat-agentcore-review-demo-app-3"


def load(name: str) -> dict:
    return copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text()))


@pytest.mark.parametrize(
    ("action", "policy"),
    [
        ("opened", "allow_duplicate_failed_only"),
        ("synchronize", "allow_duplicate_failed_only"),
        ("reopened", "allow_duplicate"),
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
    payload["sender"] = {"login": "tar-bot[bot]", "type": "Bot"}
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
    payload["sender"] = {"login": "tar-bot[bot]", "type": "Bot"}
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
    assert (result.command, result.workflow_id, result.comment_id, result.author) == (
        command,
        WF,
        555,
        "octocat",
    )


@pytest.mark.parametrize("body", ["/fixit", "please /fix", "/FIX", "", "LGTM", "/review"])
def test_non_commands_are_ignored(body):
    payload = load("issue_comment")
    payload["comment"]["body"] = body
    assert isinstance(route("issue_comment", payload, "d", CONFIG), Ignore)


def test_bot_comments_are_ignored_by_login():
    payload = load("issue_comment")
    payload["sender"] = {"login": "tar-bot[bot]", "type": "Bot"}
    assert isinstance(route("issue_comment", payload, "d", CONFIG), Ignore)


def test_bot_comments_are_ignored_by_app_id():
    payload = load("issue_comment")
    payload["comment"]["performed_via_github_app"] = {"id": 5078593}
    assert isinstance(route("issue_comment", payload, "d", CONFIG), Ignore)


def test_comments_on_plain_issues_are_ignored():
    payload = load("issue_comment")
    del payload["issue"]["pull_request"]
    assert isinstance(route("issue_comment", payload, "d", CONFIG), Ignore)


@pytest.mark.parametrize("action", ["edited", "deleted"])
def test_edited_or_deleted_comments_are_ignored(action):
    payload = load("issue_comment")
    payload["action"] = action
    assert isinstance(route("issue_comment", payload, "d", CONFIG), Ignore)


@pytest.mark.parametrize("event", ["ping", "installation", "push", "check_run"])
def test_other_events_are_ignored(event):
    assert isinstance(route(event, {}, "d", CONFIG), Ignore)


@pytest.mark.parametrize("body", [b"", b"not json", b"[1, 2]", b'"text"', b"null", b"\xff\xfe\x00"])
def test_bodies_that_are_not_json_objects_are_rejected(body):
    assert load_payload(body) is None


def test_json_object_body_is_loaded():
    assert load_payload(b'{"action": "opened"}') == {"action": "opened"}


def test_comment_without_body_is_ignored():
    payload = load("issue_comment")
    payload["comment"]["body"] = None
    assert isinstance(route("issue_comment", payload, "d", CONFIG), Ignore)

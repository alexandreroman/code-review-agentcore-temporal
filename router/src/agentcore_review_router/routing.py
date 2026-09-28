"""Pure mapping from a GitHub webhook event to the action the router must perform."""

import json
from dataclasses import dataclass, field
from typing import Literal

from agentcore_review_shared.contract import SIGNAL_PR_CLOSED, PrClosed, PrRef, PrUpdated, pr_workflow_id
from pydantic import BaseModel
from temporalio.common import WorkflowIDReusePolicy

Command = Literal["fix", "kill"]
COMMANDS: dict[str, Command] = {"/fix": "fix", "/kill": "kill"}

# Where a command was posted: "issue" for the PR's Conversation tab (issue_comment), "review" for a review
# thread, such as a reply to a finding (pull_request_review_comment). GitHub reacts on each through its own endpoint.
CommentKind = Literal["issue", "review"]


@dataclass(frozen=True)
class RouterConfig:
    prod_queue: str
    dev_queue: str
    dev_branch_prefix: str
    app_slug: str
    webhook_secret: str = field(repr=False)  # kept out of logs


@dataclass(frozen=True)
class StartOrSignal:
    workflow_id: str
    task_queue: str
    pr: PrRef
    signal: PrUpdated
    reuse_policy: WorkflowIDReusePolicy


@dataclass(frozen=True)
class SendSignal:
    workflow_id: str
    signal_name: str
    payload: BaseModel


@dataclass(frozen=True)
class RunCommand:
    command: Command
    workflow_id: str
    pr: PrRef
    comment_id: int
    comment_kind: CommentKind
    author: str
    delivery_id: str
    # The first comment of the review thread the command was posted in; None outside a thread.
    thread_root_id: int | None = None
    # The words after the command, checked by the command itself (/kill ignores them).
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True)
class ForwardReply:
    """A plain reply in a review thread: forwarded only when the thread is a finding (bot_login wrote its root)."""

    workflow_id: str
    pr: PrRef
    comment_id: int
    thread_root_id: int
    author: str
    delivery_id: str
    bot_login: str


@dataclass(frozen=True)
class Ignore:
    reason: str


Action = StartOrSignal | SendSignal | RunCommand | ForwardReply | Ignore


def route(event: str, payload: dict, delivery_id: str, config: RouterConfig) -> Action:
    if event == "pull_request":
        return _route_pull_request(payload, delivery_id, config)
    if event == "issue_comment":
        return _route_issue_comment(payload, delivery_id, config)
    if event == "pull_request_review_comment":
        return _route_command(payload, payload["pull_request"]["number"], "review", delivery_id, config)
    return Ignore(f"event {event} is not handled")


def load_payload(body: bytes) -> dict | None:
    """The webhook's JSON object, or None when a correctly signed body is not one (unexpected content type)."""
    try:
        payload = json.loads(body)
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        return None
    return payload if isinstance(payload, dict) else None


def _pr_ref(payload: dict, number: int) -> PrRef:
    repository = payload["repository"]
    return PrRef(
        owner=repository["owner"]["login"],
        repo=repository["name"],
        number=number,
        installation_id=payload["installation"]["id"],
    )


def _route_pull_request(payload: dict, delivery_id: str, config: RouterConfig) -> Action:
    action = payload.get("action")
    pull_request = payload["pull_request"]
    ref = _pr_ref(payload, pull_request["number"])
    workflow_id = pr_workflow_id(ref.owner, ref.repo, ref.number)
    if action in ("opened", "synchronize", "reopened"):
        if pull_request["head"]["ref"].startswith(config.dev_branch_prefix):
            task_queue = config.dev_queue
        else:
            task_queue = config.prod_queue
        # Reopening a closed PR asks for a fresh review, even though its previous run completed.
        if action == "reopened":
            policy = WorkflowIDReusePolicy.ALLOW_DUPLICATE
        else:
            policy = WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
        return StartOrSignal(
            workflow_id=workflow_id,
            task_queue=task_queue,
            pr=ref,
            signal=PrUpdated(head_sha=pull_request["head"]["sha"], delivery_id=delivery_id),
            reuse_policy=policy,
        )
    if action == "closed":
        merged = bool(pull_request.get("merged"))
        who = pull_request.get("merged_by") if merged else payload.get("sender")
        closed_by = (who or {}).get("login")
        return SendSignal(
            workflow_id=workflow_id,
            signal_name=SIGNAL_PR_CLOSED,
            payload=PrClosed(merged=merged, closed_by=closed_by, delivery_id=delivery_id),
        )
    return Ignore(f"pull_request action {action} is not handled")


def _route_issue_comment(payload: dict, delivery_id: str, config: RouterConfig) -> Action:
    issue = payload["issue"]
    if not issue.get("pull_request"):
        return Ignore("comment on an issue, not on a pull request")
    return _route_command(payload, issue["number"], "issue", delivery_id, config)


def _route_command(payload: dict, number: int, kind: CommentKind, delivery_id: str, config: RouterConfig) -> Action:
    """Both comment events share the same shape for the fields a command needs: action, comment and sender.

    A review comment may also be a plain reply in a thread, which the worker answers when the thread is a finding.
    """
    if payload.get("action") != "created":
        return Ignore("comment was not created")
    comment = payload["comment"]
    author = (payload.get("sender") or {}).get("login", "")
    # The GitHub App comments as "<app slug>[bot]"; a human may pick the bare slug as a user name.
    bot_login = f"{config.app_slug}[bot]"
    if author == bot_login:
        return Ignore("comment from the bot itself")
    words = (comment.get("body") or "").split()
    if not words:
        return Ignore("empty comment")
    # Only review comments belong to a thread; a top-level review comment has no in_reply_to_id.
    thread_root_id = comment.get("in_reply_to_id") if kind == "review" else None
    ref = _pr_ref(payload, number)
    workflow_id = pr_workflow_id(ref.owner, ref.repo, ref.number)
    command = COMMANDS.get(words[0])
    if command is not None:
        return RunCommand(
            command=command,
            workflow_id=workflow_id,
            pr=ref,
            comment_id=comment["id"],
            comment_kind=kind,
            author=author,
            delivery_id=delivery_id,
            thread_root_id=thread_root_id,
            arguments=tuple(words[1:]),
        )
    if thread_root_id is None:
        return Ignore("not a command")
    return ForwardReply(
        workflow_id=workflow_id,
        pr=ref,
        comment_id=comment["id"],
        thread_root_id=thread_root_id,
        author=author,
        delivery_id=delivery_id,
        bot_login=bot_login,
    )

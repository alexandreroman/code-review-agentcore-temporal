"""Pure mapping from a GitHub webhook event to the action the router must perform."""

from dataclasses import dataclass
from typing import Literal

from agentcore_review_shared.contract import (
    SIGNAL_PR_CLOSED,
    PrClosed,
    PrRef,
    PrUpdated,
    PullRequestInput,
    pr_workflow_id,
)
from pydantic import BaseModel
from temporalio.common import WorkflowIDReusePolicy

Command = Literal["fix", "kill"]
COMMANDS: dict[str, Command] = {"/fix": "fix", "/kill": "kill"}

MAX_SUMMARY_BYTES = 200  # Temporal's cap on a workflow's static summary

# Where a command was posted: "issue" for the PR's Conversation tab (issue_comment), "review" for a review
# thread, such as a reply to a finding (pull_request_review_comment). GitHub reacts on each through its own endpoint.
CommentKind = Literal["issue", "review"]


@dataclass(frozen=True)
class RouterConfig:
    prod_queue: str
    dev_queue: str
    dev_branch_prefix: str
    app_slug: str
    idle_warning_seconds: int
    idle_close_seconds: int


@dataclass(frozen=True)
class StartOrSignal:
    workflow_id: str
    task_queue: str
    input: PullRequestInput  # only a new run takes it: a running workflow keeps its own
    signal: PrUpdated
    reuse_policy: WorkflowIDReusePolicy
    summary: str  # the workflow's static summary in Temporal UI: only a new run takes it


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


def workflow_summary(number: int, title: str) -> str:
    """`#3 · Add customer search`, on a single line of at most 200 bytes, cut with an ellipsis."""
    summary = " ".join(f"#{number} · {title}".split())
    if len(summary.encode()) <= MAX_SUMMARY_BYTES:
        return summary
    ellipsis = "…"
    kept_bytes = summary.encode()[: MAX_SUMMARY_BYTES - len(ellipsis.encode())]
    # The cut may split a multibyte character: its leftover bytes are dropped.
    return kept_bytes.decode(errors="ignore") + ellipsis


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
            input=PullRequestInput(
                pr=ref,
                idle_warning_seconds=config.idle_warning_seconds,
                idle_close_seconds=config.idle_close_seconds,
                reopened=(action == "reopened"),
            ),
            signal=PrUpdated(head_sha=pull_request["head"]["sha"], delivery_id=delivery_id),
            reuse_policy=policy,
            summary=workflow_summary(ref.number, pull_request["title"]),
        )
    if action == "closed":
        merged = bool(pull_request.get("merged"))
        who = pull_request.get("merged_by") if merged else payload.get("sender")
        closed_by = (who or {}).get("login")
        return SendSignal(
            workflow_id=workflow_id,
            signal_name=SIGNAL_PR_CLOSED,
            payload=PrClosed(merged=merged, closed_by=closed_by),
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

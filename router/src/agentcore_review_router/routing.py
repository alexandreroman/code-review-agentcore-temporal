"""Pure mapping from a GitHub webhook event to the action the router must perform."""

import re
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
from agentcore_review_shared.summaries import fit
from pydantic import BaseModel
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

Command = Literal["fix", "kill"]
COMMANDS: dict[str, Command] = {"/fix": "fix", "/kill": "kill"}

# Where a command was posted: "issue" for the PR's Conversation tab (issue_comment), "review" for a review
# thread, such as a reply to a finding (pull_request_review_comment). GitHub reacts on each through its own endpoint.
CommentKind = Literal["issue", "review"]

# The parts of a comment where a mention notifies nobody, removed in this order: a code block runs to its closing
# fence (or to the end when unclosed) and may hold anything, so it goes first.
_UNNOTIFIED_PARTS = (
    re.compile(r"^[ \t]*(`{3,}|~{3,}).*?(^[ \t]*\1|\Z)", re.MULTILINE | re.DOTALL),  # fenced code block
    re.compile(r"<!--.*?(-->|\Z)", re.DOTALL),  # HTML comment
    re.compile(r"`[^`]*`"),  # inline code
    re.compile(r"^[ \t]*>.*$", re.MULTILINE),  # quoted line
)


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
    reuse_policy: WorkflowIDReusePolicy  # against a closed run
    conflict_policy: WorkflowIDConflictPolicy  # against a running one
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
    """A plain comment for the worker to answer: a reply in a review thread, forwarded only when the thread is a
    finding (bot_login wrote its root), or a comment in the Conversation."""

    workflow_id: str
    pr: PrRef
    comment_id: int
    # The first comment of the review thread the reply was posted in; None in the Conversation.
    thread_root_id: int | None
    author: str
    delivery_id: str
    bot_login: str
    # The Conversation comment mentions the bot: it is addressed to it.
    mentioned: bool


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
    """`#3 · Add customer search`, made to fit Temporal UI like the worker's summaries."""
    return fit(f"#{number} · {title}")


def mentions_bot(body: str, app_slug: str) -> bool:
    """Whether the comment mentions @<app slug> or @<app slug>[bot], in any case, as a whole login.

    GitHub logins hold letters, digits and hyphens: @tar-bot-fan names another user, @tar-bot[botfan] is no bot
    login, and an address such as ops@tar-bot mentions nobody. A mention in a fenced code block, inline code, an
    HTML comment or a quoted line does not count: GitHub notifies nobody for those, and a quote reply repeats an
    earlier mention.
    """
    for part in _UNNOTIFIED_PARTS:
        body = part.sub(" ", body)
    pattern = rf"(?<![\w-])@{re.escape(app_slug)}(\[bot\])?(?![\w-]|\[bot)"
    return re.search(pattern, body, re.IGNORECASE) is not None


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
        # Reopening a PR asks for a fresh review. A run still running under this ID belongs to the closed PR (it may be
        # finishing an action or its close) and signalling it would lose the reopen, so the new run terminates it and
        # takes over its state.
        if action == "reopened":
            reuse_policy = WorkflowIDReusePolicy.ALLOW_DUPLICATE
            conflict_policy = WorkflowIDConflictPolicy.TERMINATE_EXISTING
        else:
            reuse_policy = WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
            conflict_policy = WorkflowIDConflictPolicy.USE_EXISTING
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
            reuse_policy=reuse_policy,
            conflict_policy=conflict_policy,
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

    Any other comment in the Conversation goes to the worker, which answers it when it mentions the bot or calls for
    an answer. A review comment may be a plain reply in a thread, which the worker answers when the thread is a
    finding; a review thread a human started is left alone.
    """
    if payload.get("action") != "created":
        return Ignore("comment was not created")
    comment = payload["comment"]
    author = (payload.get("sender") or {}).get("login", "")
    # The GitHub App comments as "<app slug>[bot]"; a human may pick the bare slug as a user name.
    bot_login = f"{config.app_slug}[bot]"
    if author == bot_login:
        return Ignore("comment from the bot itself")
    body = comment.get("body") or ""
    words = body.split()
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
    if kind == "review" and thread_root_id is None:
        return Ignore("not a command")
    return ForwardReply(
        workflow_id=workflow_id,
        pr=ref,
        comment_id=comment["id"],
        thread_root_id=thread_root_id,
        author=author,
        delivery_id=delivery_id,
        bot_login=bot_login,
        # In a finding's thread, every reply gets an answer: a mention changes nothing there.
        mentioned=kind == "issue" and mentions_bot(body, config.app_slug),
    )

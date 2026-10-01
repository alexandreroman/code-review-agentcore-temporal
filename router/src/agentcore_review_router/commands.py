"""The /fix and /kill commands: permission check, a Temporal signal or AgentCore session stops, then feedback on
the pull request (a reaction or a short comment). Plain replies to a finding go through the same permission check
before reaching the pull request workflow, which answers them.

A /kill whose stops are not all confirmed within the webhook's budget hands the rest to an asynchronous
invocation of this same Lambda, which finishes the stops and posts the comment.
"""

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any, Literal

from agentcore_review_shared.contract import (
    SIGNAL_COMMENT_POSTED,
    SIGNAL_FIX_REQUESTED,
    AgentCoreSession,
    CommentPosted,
    FixRequested,
    PrRef,
)
from agentcore_review_shared.github import GitHubApp, GitHubError
from pydantic import BaseModel
from temporalio.client import Client

from . import runtime, temporal_ops
from .routing import CommentKind, ForwardReply, RunCommand
from .rules import (
    DEV_KILL_REPLY,
    FIX_USAGE_REPLY,
    NO_REVIEW_REPLY,
    NO_WORKER_REPLY,
    REACTION_ACK,
    REACTION_DENIED,
    REACTION_KILL,
    KillTally,
    StopOutcome,
    can_run_commands,
    fix_finding_ids,
    kill_comment,
    kill_targets,
)
from .sessions import stop_sessions

logger = logging.getLogger(__name__)

# Seconds kept after the stops for the reaction, the comment and the HTTP response.
REPLY_RESERVE = 2.5


class KillFollowup(BaseModel):
    """Payload of the asynchronous self-invocation that finishes a /kill."""

    router_task: Literal["kill"] = "kill"  # tells the handler this event is not a webhook
    pr: PrRef
    comment_id: int
    comment_kind: CommentKind
    delivery_id: str
    sessions: list[AgentCoreSession]
    tally: KillTally


async def run_command(command: RunCommand, client: Client, deadline: float, fields: dict[str, Any]) -> str:
    app = runtime.github()
    permission = await _permission(app, command.pr, command.author)
    if not can_run_commands(permission):
        await _best_effort(_react(app, command.pr, command.comment_kind, command.comment_id, REACTION_DENIED), fields)
        return f"/{command.command} refused: {command.author or 'unknown user'} has {permission or 'no'} access"
    if command.command == "fix":
        return await _fix(command, client, app, fields)
    return await _kill(command, client, app, deadline, fields)


async def forward_reply(action: ForwardReply, client: Client, fields: dict[str, Any]) -> str:
    """A plain reply in a finding's thread: checked like a command, then queued in the workflow, which answers.

    A plain reply is not addressed to the bot: when ignored, it gets neither a reaction nor a comment.
    """
    app = runtime.github()
    if await _comment_author(app, action.pr, action.thread_root_id) != action.bot_login:
        return "reply in a thread that is not a finding"
    permission = await _permission(app, action.pr, action.author)
    if not can_run_commands(permission):
        return f"reply ignored: {action.author or 'unknown user'} has {permission or 'no'} access"
    posted = CommentPosted(
        comment_id=action.comment_id,
        thread_root_id=action.thread_root_id,
        author=action.author,
        delivery_id=action.delivery_id,
    )
    if not await temporal_ops.signal(client, action.workflow_id, SIGNAL_COMMENT_POSTED, posted):
        return "reply ignored: no review in progress"
    await _best_effort(_react(app, action.pr, "review", action.comment_id, REACTION_ACK), fields)
    return f"signal {SIGNAL_COMMENT_POSTED} to {action.workflow_id}"


async def finish_kill(event: dict, deadline: float) -> None:
    """Asynchronous self-invocation: stops the sessions the webhook invocation could not confirm in time."""
    fields = {"delivery": event.get("delivery_id", "")}
    try:
        followup = KillFollowup.model_validate(event)
        outcomes = await _stop(followup.sessions, deadline, fields)
        tally = followup.tally.add(outcomes.values())
        await _kill_feedback(runtime.github(), followup.pr, followup.comment_kind, followup.comment_id, tally, fields)
        logger.info("kill follow-up", extra=fields | {"outcome": kill_comment(tally)})
    except Exception:
        # Asynchronous invocations are never retried (event invoke config): a failure only logs.
        logger.exception("kill follow-up failed", extra=fields)


async def _fix(command: RunCommand, client: Client, app: GitHubApp, fields: dict[str, Any]) -> str:
    finding_ids = fix_finding_ids(command.arguments)
    if finding_ids is None:
        await _best_effort(_react(app, command.pr, command.comment_kind, command.comment_id, REACTION_DENIED), fields)
        await _best_effort(_reply(app, command.pr, FIX_USAGE_REPLY, command.thread_root_id), fields)
        return "/fix refused: arguments are not finding IDs"
    requested = FixRequested(
        requested_by=command.author,
        delivery_id=command.delivery_id,
        thread_root_id=command.thread_root_id,
        finding_ids=finding_ids,
    )
    if await temporal_ops.signal(client, command.workflow_id, SIGNAL_FIX_REQUESTED, requested):
        await _best_effort(_react(app, command.pr, command.comment_kind, command.comment_id, REACTION_ACK), fields)
        return f"signal {SIGNAL_FIX_REQUESTED} to {command.workflow_id}"
    await _best_effort(_reply(app, command.pr, NO_REVIEW_REPLY), fields)
    return "/fix: no review in progress"


async def _kill(command: RunCommand, client: Client, app: GitHubApp, deadline: float, fields: dict[str, Any]) -> str:
    settings = runtime.settings()
    queue = await temporal_ops.workflow_task_queue(client, command.workflow_id)
    # A dev-queue PR is served by a local worker; with no workflow, /kill still clears production.
    if queue == settings.dev_task_queue:
        await _best_effort(_reply(app, command.pr, DEV_KILL_REPLY), fields)
        return "/kill: dev worker"
    targets: list[AgentCoreSession] = []
    if settings.runtime_arn:  # empty until the first make deploy: no AgentCore worker yet
        targets = kill_targets(poller.identity for poller in await temporal_ops.pollers(client, settings.task_queue))
    if not targets:
        await _best_effort(_reply(app, command.pr, NO_WORKER_REPLY), fields)
        return "/kill: no active worker"
    outcomes = await _stop(targets, deadline, fields)
    leftover = [session for session, outcome in outcomes.items() if outcome == "retry"]
    if leftover:
        confirmed = KillTally().add(outcome for outcome in outcomes.values() if outcome != "retry")
        followup = KillFollowup(
            pr=command.pr,
            comment_id=command.comment_id,
            comment_kind=command.comment_kind,
            delivery_id=command.delivery_id,
            sessions=leftover,
            tally=confirmed,
        )
        try:
            runtime.lambda_client().invoke(
                FunctionName=settings.function_name, InvocationType="Event", Payload=followup.model_dump_json()
            )
            return f"/kill: {len(leftover)} unconfirmed stop(s) handed to an asynchronous invocation"
        except Exception:
            logger.exception("asynchronous /kill follow-up not sent", extra=fields)
    # Unconfirmed stops count as failed.
    tally = KillTally().add(outcomes.values())
    await _kill_feedback(app, command.pr, command.comment_kind, command.comment_id, tally, fields)
    return f"/kill: {kill_comment(tally)}"


async def _stop(
    sessions: list[AgentCoreSession], deadline: float, fields: dict[str, Any]
) -> dict[AgentCoreSession, StopOutcome]:
    settings = runtime.settings()
    return await asyncio.to_thread(
        stop_sessions, runtime.agentcore(), settings.runtime_arn, sessions, deadline - REPLY_RESERVE, fields
    )


async def _kill_feedback(
    app: GitHubApp, pr: PrRef, comment_kind: CommentKind, comment_id: int, tally: KillTally, fields: dict[str, Any]
) -> None:
    await _best_effort(_react(app, pr, comment_kind, comment_id, REACTION_KILL), fields)
    await _best_effort(_reply(app, pr, kill_comment(tally)), fields)


async def _permission(app: GitHubApp, pr: PrRef, user: str) -> str | None:
    """The user's permission on the repository, or None when they are not a collaborator."""
    collaborator = await _get_json_or_none(app, pr, f"/collaborators/{user}/permission")
    return None if collaborator is None else collaborator.get("permission")


async def _comment_author(app: GitHubApp, pr: PrRef, comment_id: int) -> str | None:
    """The author of a review comment, or None when it was deleted."""
    comment = await _get_json_or_none(app, pr, f"/pulls/comments/{comment_id}")
    return None if comment is None else (comment.get("user") or {}).get("login")


async def _get_json_or_none(app: GitHubApp, pr: PrRef, path: str) -> dict | None:
    """GET a path under the pull request's repository; None when GitHub answers 404."""
    try:
        response = await app.request(pr.installation_id, "GET", f"/repos/{pr.owner}/{pr.repo}{path}")
    except GitHubError as error:
        if error.status == 404:
            return None
        raise
    return response.json()


async def _react(app: GitHubApp, pr: PrRef, comment_kind: CommentKind, comment_id: int, content: str) -> None:
    kind = "pulls" if comment_kind == "review" else "issues"
    path = f"/repos/{pr.owner}/{pr.repo}/{kind}/comments/{comment_id}/reactions"
    await app.request(pr.installation_id, "POST", path, json={"content": content})


async def _reply(app: GitHubApp, pr: PrRef, body: str, thread_root_id: int | None = None) -> None:
    """A comment in the Conversation, or a reply in the review thread that starts with thread_root_id."""
    if thread_root_id is None:
        path = f"/repos/{pr.owner}/{pr.repo}/issues/{pr.number}/comments"
    else:
        # GitHub answers a thread through its first comment: replies to a reply are not supported.
        path = f"/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}/comments/{thread_root_id}/replies"
    await app.request(pr.installation_id, "POST", path, json={"body": body})


async def _best_effort(call: Awaitable[None], fields: dict[str, Any]) -> None:
    """Feedback follows the action: a failure is logged, never turned into a 500 that would invite a redelivery."""
    try:
        await call
    except Exception:
        logger.exception("GitHub feedback failed", extra=fields)

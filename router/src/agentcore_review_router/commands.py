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
    NO_REVIEW_REPLY,
    NO_WORKER_REPLY,
    REACTION_DENIED,
    REACTION_FIX,
    REACTION_KILL,
    KillTally,
    StopOutcome,
    can_run_commands,
    is_bot_login,
    kill_comment,
    kill_targets,
)
from .sessions import stop_sessions

logger = logging.getLogger(__name__)

FOLLOWUP_KEY = "router_task"
# Seconds kept after the stops for the reaction, the comment and the HTTP response.
REPLY_RESERVE = 2.5


class KillFollowup(BaseModel):
    """Payload of the asynchronous self-invocation that finishes a /kill."""

    router_task: Literal["kill"] = "kill"
    pr: PrRef
    comment_id: int
    # The default keeps valid the follow-ups an older router version queued without this field.
    comment_kind: CommentKind = "issue"
    delivery_id: str
    sessions: list[AgentCoreSession]
    tally: KillTally


async def run(command: RunCommand, client: Client, deadline: float) -> str:
    app = runtime.github()
    fields = {"delivery": command.delivery_id, "workflow_id": command.workflow_id}
    permission = await _permission(app, command.pr, command.author)
    if not can_run_commands(permission):
        await _best_effort(_react(app, command.pr, command.comment_kind, command.comment_id, REACTION_DENIED), fields)
        return f"/{command.command} refused: {command.author or 'unknown user'} has {permission or 'no'} access"
    if command.command == "fix":
        return await _fix(command, client, app, fields)
    return await _kill(command, client, app, deadline, fields)


async def forward_reply(action: ForwardReply, client: Client) -> str:
    """A plain reply in a finding's thread: checked like a command, then queued in the workflow, which answers."""
    app = runtime.github()
    fields = {"delivery": action.delivery_id, "workflow_id": action.workflow_id}
    # Checked here rather than in the workflow: a human thread gets neither 👀 nor a signal.
    if not is_bot_login(await _comment_author(app, action.pr, action.thread_root_id), action.bot_login):
        return "reply in a thread that is not a finding"
    permission = await _permission(app, action.pr, action.author)
    if not can_run_commands(permission):
        # Unlike a command, a plain reply is not addressed to the bot: no 😕 reaction.
        return f"reply ignored: {action.author or 'unknown user'} has {permission or 'no'} access"
    posted = CommentPosted(
        comment_id=action.comment_id,
        thread_root_id=action.thread_root_id,
        author=action.author,
        delivery_id=action.delivery_id,
    )
    # No "no review in progress" comment here: a plain reply is not addressed to the bot.
    if not await temporal_ops.signal(client, action.workflow_id, SIGNAL_COMMENT_POSTED, posted):
        return "reply ignored: no review in progress"
    await _best_effort(_react(app, action.pr, "review", action.comment_id, REACTION_FIX), fields)
    return f"signal {SIGNAL_COMMENT_POSTED} to {action.workflow_id}"


async def finish_kill(event: dict, deadline: float) -> None:
    """Asynchronous self-invocation: stops the sessions the webhook invocation could not confirm in time."""
    followup = KillFollowup.model_validate(event)
    fields = {"delivery": followup.delivery_id}
    outcomes = await _stop(followup.sessions, deadline, fields)
    tally = followup.tally.add(outcomes.values())
    await _kill_feedback(runtime.github(), followup.pr, followup.comment_kind, followup.comment_id, tally, fields)
    logger.info("kill follow-up", extra=fields | {"outcome": kill_comment(tally)})


async def _fix(command: RunCommand, client: Client, app: GitHubApp, fields: dict[str, Any]) -> str:
    requested = FixRequested(
        requested_by=command.author, delivery_id=command.delivery_id, thread_root_id=command.thread_root_id
    )
    if await temporal_ops.signal(client, command.workflow_id, SIGNAL_FIX_REQUESTED, requested):
        await _best_effort(_react(app, command.pr, command.comment_kind, command.comment_id, REACTION_FIX), fields)
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
    targets = kill_targets(await temporal_ops.poller_identities(client, settings.task_queue))
    if not targets or not settings.runtime_arn:
        await _best_effort(_reply(app, command.pr, NO_WORKER_REPLY), fields)
        return "/kill: no active worker"
    outcomes = await _stop(targets, deadline, fields)
    leftover = [session for session, outcome in outcomes.items() if outcome == "retry"]
    tally = KillTally().add(outcome for outcome in outcomes.values() if outcome != "retry")
    if leftover:
        followup = KillFollowup(
            pr=command.pr,
            comment_id=command.comment_id,
            comment_kind=command.comment_kind,
            delivery_id=command.delivery_id,
            sessions=leftover,
            tally=tally,
        )
        try:
            runtime.lambda_client().invoke(
                FunctionName=settings.function_name, InvocationType="Event", Payload=followup.model_dump_json()
            )
            return f"/kill: {len(leftover)} unconfirmed stop(s) handed to an asynchronous invocation"
        except Exception:
            logger.exception("asynchronous /kill follow-up not sent", extra=fields)
            tally = tally.add(["failed"] * len(leftover))
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
    try:
        response = await app.request(
            pr.installation_id, "GET", f"/repos/{pr.owner}/{pr.repo}/collaborators/{user}/permission"
        )
    except GitHubError as error:
        if error.status == 404:  # not a collaborator
            return None
        raise
    return response.json().get("permission")


async def _comment_author(app: GitHubApp, pr: PrRef, comment_id: int) -> str | None:
    """The author of a review comment, or None when it was deleted."""
    try:
        response = await app.request(
            pr.installation_id, "GET", f"/repos/{pr.owner}/{pr.repo}/pulls/comments/{comment_id}"
        )
    except GitHubError as error:
        if error.status == 404:
            return None
        raise
    return (response.json().get("user") or {}).get("login")


async def _react(app: GitHubApp, pr: PrRef, comment_kind: CommentKind, comment_id: int, content: str) -> None:
    if comment_kind == "review":
        path = f"/repos/{pr.owner}/{pr.repo}/pulls/comments/{comment_id}/reactions"
    else:
        path = f"/repos/{pr.owner}/{pr.repo}/issues/comments/{comment_id}/reactions"
    await app.request(pr.installation_id, "POST", path, json={"content": content})


async def _reply(app: GitHubApp, pr: PrRef, body: str) -> None:
    path = f"/repos/{pr.owner}/{pr.repo}/issues/{pr.number}/comments"
    await app.request(pr.installation_id, "POST", path, json={"body": body})


async def _best_effort(call: Awaitable[None], fields: dict[str, Any]) -> None:
    """Feedback follows the action: a failure is logged, never turned into a 500 that would invite a redelivery."""
    try:
        await call
    except Exception:
        logger.exception("GitHub feedback failed", extra=fields)

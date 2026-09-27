"""Pure mapping from a GitHub webhook event to the action the router must perform."""

import json
from dataclasses import dataclass
from typing import Literal

from agentcore_review_shared.contract import SIGNAL_PR_CLOSED, PrClosed, PrRef, PrUpdated, pr_workflow_id
from pydantic import BaseModel
from temporalio.common import WorkflowIDReusePolicy

COMMANDS: dict[str, Literal["fix", "kill"]] = {"/fix": "fix", "/kill": "kill"}


@dataclass(frozen=True)
class RouterConfig:
    prod_queue: str
    dev_queue: str
    dev_branch_prefix: str
    app_slug: str


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
    command: Literal["fix", "kill"]
    workflow_id: str
    pr: PrRef
    comment_id: int
    author: str
    delivery_id: str


@dataclass(frozen=True)
class Ignore:
    reason: str


Action = StartOrSignal | SendSignal | RunCommand | Ignore


def route(event: str, payload: dict, delivery_id: str, config: RouterConfig) -> Action:
    if event == "pull_request":
        return _route_pull_request(payload, delivery_id, config)
    if event == "issue_comment":
        return _route_comment(payload, delivery_id, config)
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
        dev = pull_request["head"]["ref"].startswith(config.dev_branch_prefix)
        # Reopening a closed PR asks for a fresh review, even though its previous run completed.
        if action == "reopened":
            policy = WorkflowIDReusePolicy.ALLOW_DUPLICATE
        else:
            policy = WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
        signal = PrUpdated(head_sha=pull_request["head"]["sha"], delivery_id=delivery_id)
        return StartOrSignal(workflow_id, config.dev_queue if dev else config.prod_queue, ref, signal, policy)
    if action == "closed":
        merged = bool(pull_request.get("merged"))
        who = pull_request.get("merged_by") if merged else payload.get("sender")
        closed_by = (who or {}).get("login")
        return SendSignal(
            workflow_id, SIGNAL_PR_CLOSED, PrClosed(merged=merged, closed_by=closed_by, delivery_id=delivery_id)
        )
    return Ignore(f"pull_request action {action} is not handled")


def _route_comment(payload: dict, delivery_id: str, config: RouterConfig) -> Action:
    if payload.get("action") != "created":
        return Ignore("comment was not created")
    issue = payload["issue"]
    if not issue.get("pull_request"):
        return Ignore("comment on an issue, not on a pull request")
    comment = payload["comment"]
    sender = payload.get("sender") or {}
    if sender.get("login") == f"{config.app_slug}[bot]":
        return Ignore("comment from the bot itself")
    words = (comment.get("body") or "").split()
    command = COMMANDS.get(words[0]) if words else None
    if command is None:
        return Ignore("not a command")
    ref = _pr_ref(payload, issue["number"])
    workflow_id = pr_workflow_id(ref.owner, ref.repo, ref.number)
    return RunCommand(command, workflow_id, ref, comment["id"], sender.get("login", ""), delivery_id)

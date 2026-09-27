"""Lambda entry point behind the Function URL: verifies, routes and acts on GitHub webhooks.

Replies 202 (action taken), 204 (event ignored), 400 (signed body that is not a webhook payload), 401 (invalid
signature), 500 (Temporal or GitHub error; GitHub never redelivers on its own) or 503 (the GitHub App secret does
not exist yet). The same function receives its own asynchronous invocations, which finish a /kill that did not
fit in the webhook's 10 s. Logs are JSON (the function's log format); every line carries the delivery ID.
"""

import logging
import time
from typing import Any

from agentcore_review_shared.secrets import GitHubAppSecret

from . import commands, runtime, temporal_ops
from .routing import Ignore, RouterConfig, RunCommand, SendSignal, StartOrSignal, load_payload, route
from .signature import decode_body, verify_signature

logger = logging.getLogger(__name__)

Reply = tuple[int, str]


def handler(event: dict, context: Any) -> dict:
    deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000
    if event.get(commands.FOLLOWUP_KEY) == "kill":
        runtime.run(_finish_kill(event, deadline))
        return {}
    return runtime.run(_handle_webhook(event, deadline))


async def _handle_webhook(event: dict, deadline: float) -> dict:
    started = time.monotonic()
    headers = {name.lower(): value for name, value in (event.get("headers") or {}).items()}
    fields: dict[str, Any] = {
        "delivery": headers.get("x-github-delivery", ""),
        "event": headers.get("x-github-event", ""),
    }
    status, outcome = await _process(event, headers, fields, deadline)
    duration_ms = round((time.monotonic() - started) * 1000)
    logger.info("webhook", extra=fields | {"status": status, "outcome": outcome, "duration_ms": duration_ms})
    # A 204 has no body; the other replies show their outcome in GitHub's "Recent Deliveries".
    return {"statusCode": status} if status == 204 else {"statusCode": status, "body": outcome}


async def _process(event: dict, headers: dict[str, str], fields: dict[str, Any], deadline: float) -> Reply:
    body = decode_body(event)
    signature = headers.get("x-hub-signature-256")
    loaded = _load_router_config(fields)
    valid = loaded is not None and verify_signature(loaded[0].webhook_secret, body, signature)
    if loaded is not None and not valid:
        # A re-registered GitHub App rotates the webhook secret: a warm container's cache is stale
        # exactly once, so retry against a fresh secret before answering 401 for good.
        runtime.clear_github_app_secret()
        loaded = _load_router_config(fields)
        valid = loaded is not None and verify_signature(loaded[0].webhook_secret, body, signature)
    if loaded is None:
        return 503, "router not configured"
    if not valid:
        return 401, "invalid signature"
    config = loaded[1]
    payload = load_payload(body)
    if payload is None:
        return 400, "body is not a JSON object"
    fields["action"] = payload.get("action")
    try:
        action = route(fields["event"], payload, fields["delivery"], config)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        # ValueError also covers pydantic's ValidationError, raised when a field (e.g. head.sha) is null.
        logger.warning("unexpected payload shape", extra=fields | {"error": repr(error)})
        return 400, "unexpected payload shape"
    if isinstance(action, Ignore):
        return 204, action.reason
    fields["workflow_id"] = action.workflow_id
    try:
        return await _act(action, fields, deadline)
    except Exception:
        logger.exception("action failed", extra=fields)
        return 500, "action failed (see the router logs)"


def _load_router_config(fields: dict[str, Any]) -> tuple[GitHubAppSecret, RouterConfig] | None:
    try:
        return runtime.github_app_secret(), runtime.router_config()
    except Exception:
        logger.exception("router not configured (has make github-app run?)", extra=fields)
        return None


async def _act(action: StartOrSignal | SendSignal | RunCommand, fields: dict[str, Any], deadline: float) -> Reply:
    client = await runtime.temporal_client()
    if isinstance(action, StartOrSignal):
        fields["task_queue"] = action.task_queue
        if await temporal_ops.start_or_signal(client, action):
            return 202, f"signal-with-start {action.workflow_id} on {action.task_queue}"
        return 204, "pull request workflow already finished"
    if isinstance(action, SendSignal):
        if await temporal_ops.signal(client, action.workflow_id, action.signal_name, action.payload):
            return 202, f"signal {action.signal_name} to {action.workflow_id}"
        return 204, "no running workflow"
    return 202, await commands.run(action, client, deadline)


async def _finish_kill(event: dict, deadline: float) -> None:
    try:
        await commands.finish_kill(event, deadline)
    except Exception:
        # Asynchronous invocations are never retried (event invoke config): a failure only logs.
        logger.exception("kill follow-up failed", extra={"delivery": event.get("delivery_id", "")})

"""Lambda entry point behind the Function URL or API Gateway: verifies, routes and acts on GitHub webhooks.

Replies 202 (action taken), 204 (event ignored), 400 (signed body that is not a webhook payload), 401 (invalid
signature), 500 (Temporal or GitHub error; GitHub never redelivers on its own) or 503 (the GitHub App secret does
not exist yet). The same function receives its own asynchronous invocations, which finish a /kill that did not
fit in the webhook's 10 s. Logs are JSON (the function's log format); every line carries the delivery ID.
"""

import json
import logging
import time
from typing import Any

from . import commands, runtime, temporal_ops
from .routing import ForwardReply, Ignore, RunCommand, SendSignal, StartOrSignal, route
from .signature import decode_body, verify_signature

logger = logging.getLogger(__name__)

Reply = tuple[int, str]


def handler(event: dict, context: Any) -> dict:
    deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000
    if event.get("router_task") == "kill":
        runtime.run(commands.finish_kill(event, deadline))
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
    try:
        signed = _is_signed(body, headers.get("x-hub-signature-256"))
    except Exception:
        logger.exception("router not configured (has make github-app run?)", extra=fields)
        return 503, "router not configured"
    if not signed:
        return 401, "invalid signature"
    try:
        payload = json.loads(body)
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        payload = None
    if not isinstance(payload, dict):
        return 400, "body is not a JSON object"
    fields["action"] = payload.get("action")
    config = runtime.router_config()
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


def _is_signed(body: bytes, signature: str | None) -> bool:
    """Raises when the router is not configured (the GitHub App secret does not exist yet)."""
    if verify_signature(runtime.github_app_secret().webhook_secret, body, signature):
        return True
    # A re-registered GitHub App rotates the webhook secret: a warm container's cache is stale exactly once, so
    # check against a fresh secret (one Secrets Manager call per unsigned request) before refusing the signature.
    runtime.refresh_github_app_secret()
    return verify_signature(runtime.github_app_secret().webhook_secret, body, signature)


async def _act(
    action: StartOrSignal | SendSignal | RunCommand | ForwardReply, fields: dict[str, Any], deadline: float
) -> Reply:
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
    if isinstance(action, ForwardReply):
        return 202, await commands.forward_reply(action, client, fields)
    return 202, await commands.run_command(action, client, deadline, fields)

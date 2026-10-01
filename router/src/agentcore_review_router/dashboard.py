"""The status snapshot behind /dashboard.json: aggregates read from Temporal, kept TTL seconds per container.

Only the production task queue and visibility are read: a workflow query needs a worker and would wake an AgentCore
session. Each block fails on its own: it is null in the JSON. A burst of page refreshes
costs at most one round of Temporal calls per container and per TTL.
"""

import asyncio
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agentcore_review_shared.contract import (
    DISCUSSION_WORKFLOW,
    FIXER_WORKFLOW,
    PULL_REQUEST_WORKFLOW,
    REVIEWER_WORKFLOW,
    SYNTHESIS_WORKFLOW,
)
from botocore.exceptions import ClientError
from temporalio.client import Client

from . import runtime, temporal_ops
from .pages import etag_of
from .rules import kill_targets

logger = logging.getLogger(__name__)

TTL = 15.0
CALL_TIMEOUT = timedelta(seconds=3)
# Bounds the Temporal calls and the client's connection, well within the Lambda's 10 s. On a cold container the
# certificate read before the connection is a synchronous boto3 call that asyncio.timeout cannot interrupt: its own
# config bounds it (runtime.SECRETS_CALL_CONFIG).
READ_BUDGET = 6.0
# The server lists pollers seen in the last ~5 minutes. An idle worker's long polls last about a minute, so a live
# session can show a last access close to 60 s old: 75 s keeps it counted.
ACTIVE_WITHIN = timedelta(seconds=75)
AGENT_WORKFLOWS = (REVIEWER_WORKFLOW, FIXER_WORKFLOW, SYNTHESIS_WORKFLOW, DISCUSSION_WORKFLOW)


@dataclass(frozen=True)
class Snapshot:
    body: bytes
    etag: str
    taken_at: float  # time.monotonic()


_snapshot: Snapshot | None = None


async def snapshot() -> Snapshot:
    global _snapshot
    if _snapshot is None or time.monotonic() - _snapshot.taken_at >= TTL:
        body = await _read()
        _snapshot = Snapshot(body, etag_of(body), time.monotonic())
    return _snapshot


def active_sessions(pollers: Iterable[temporal_ops.Poller], now: datetime) -> int:
    """AgentCore sessions seen within ACTIVE_WITHIN, once each: a worker polls two task types."""
    return len(kill_targets(poller.identity for poller in pollers if now - poller.last_access < ACTIVE_WITHIN))


def review_queries(task_queue: str, now: datetime) -> dict[str, str]:
    """Visibility queries per figure. Completed leaves out the runs closed by a continue-as-new."""
    queue = f"TaskQueue = '{task_queue}'"
    agents = ", ".join(f"'{name}'" for name in AGENT_WORKFLOWS)
    since = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "running": f"WorkflowType = '{PULL_REQUEST_WORKFLOW}' AND ExecutionStatus = 'Running' AND {queue}",
        "agents_running": f"WorkflowType IN ({agents}) AND ExecutionStatus = 'Running' AND {queue}",
        "completed_24h": (
            f"WorkflowType = '{PULL_REQUEST_WORKFLOW}' AND ExecutionStatus = 'Completed' "
            f"AND CloseTime > '{since}' AND {queue}"
        ),
    }


def snapshot_json(deployed: bool, sessions: int | None, reviews: dict[str, int] | None) -> bytes:
    """The JSON document; a block that could not be read is null."""
    document = {
        "deployed": deployed,
        "sessions": None if sessions is None else {"active": sessions},
        "reviews": reviews,
    }
    return json.dumps(document, separators=(",", ":")).encode()


async def _read() -> bytes:
    try:
        async with asyncio.timeout(READ_BUDGET):
            client = await runtime.temporal_client()
            task_queue = runtime.settings().task_queue
            now = datetime.now(UTC)
            sessions, reviews = await asyncio.gather(
                _sessions(client, task_queue, now), _reviews(client, task_queue, now)
            )
            return snapshot_json(True, sessions, reviews)
    except Exception as error:  # TimeoutError included
        if isinstance(error, ClientError) and error.response["Error"]["Code"] == "ResourceNotFoundException":
            return snapshot_json(False, None, None)  # no Temporal certificate before the first make up
        logger.exception("status block unavailable", extra={"block": "client"})
        return snapshot_json(True, None, None)


async def _sessions(client: Client, task_queue: str, now: datetime) -> int | None:
    try:
        return active_sessions(await temporal_ops.pollers(client, task_queue, CALL_TIMEOUT), now)
    except Exception:
        logger.exception("status block unavailable", extra={"block": "sessions"})
        return None


async def _reviews(client: Client, task_queue: str, now: datetime) -> dict[str, int] | None:
    queries = review_queries(task_queue, now)
    try:
        counts = await asyncio.gather(
            *(client.count_workflows(query, rpc_timeout=CALL_TIMEOUT) for query in queries.values())
        )
    except Exception:
        logger.exception("status block unavailable", extra={"block": "reviews"})
        return None
    return {name: count.count for name, count in zip(queries, counts, strict=True)}

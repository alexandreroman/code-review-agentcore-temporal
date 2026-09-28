"""StopRuntimeSession on several AgentCore sessions in parallel, within a deadline, retried on transient errors."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from agentcore_review_shared.contract import AgentCoreSession
from botocore.exceptions import BotoCoreError, ClientError

from .rules import StopOutcome, stop_outcome

logger = logging.getLogger(__name__)

MAX_PARALLEL_STOPS = 8
RETRY_DELAY = 0.5


def stop_sessions(
    client: Any, runtime_arn: str, sessions: list[AgentCoreSession], deadline: float, fields: dict[str, Any]
) -> dict[AgentCoreSession, StopOutcome]:
    """Outcome per session; "retry" marks a stop not confirmed before `deadline` (time.monotonic() clock)."""
    outcomes: dict[AgentCoreSession, StopOutcome] = dict.fromkeys(sessions, "retry")
    pool = ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_STOPS, len(sessions)))
    futures = {pool.submit(_stop, client, runtime_arn, session, deadline, fields): session for session in sessions}
    done, _ = wait(futures, timeout=max(0.0, deadline - time.monotonic()))
    # A call still running keeps its thread until its own read timeout; its result is dropped.
    pool.shutdown(wait=False, cancel_futures=True)
    for future in done:
        outcomes[futures[future]] = future.result()
    return outcomes


def _stop(
    client: Any, runtime_arn: str, session: AgentCoreSession, deadline: float, fields: dict[str, Any]
) -> StopOutcome:
    while True:
        started = time.monotonic()
        try:
            client.stop_runtime_session(
                agentRuntimeArn=runtime_arn, runtimeSessionId=session.session_id, qualifier=session.endpoint
            )
            code = None
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "ClientError")
        except BotoCoreError:  # connect or read timeout, connection error
            code = "timeout"
        outcome = stop_outcome(code)
        logger.info(
            "stop session",
            extra=fields
            | {
                "endpoint": session.endpoint,
                "session": session.session_id,
                "code": code,
                "outcome": outcome,
                "duration_ms": round((time.monotonic() - started) * 1000),
            },
        )
        if outcome != "retry" or time.monotonic() + RETRY_DELAY >= deadline:
            return outcome
        time.sleep(RETRY_DELAY)

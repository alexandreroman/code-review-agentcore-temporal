"""AgentCore entry point. Each session runs one worker, which drains after idling and then frees the session."""

import asyncio
import os

from agentcore_review_shared.identity import agentcore_identity
from agentcore_review_shared.secrets import TemporalCertSecret
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .aws import read_secret
from .drain import ActivityTracker
from .registry import plugins
from .runtime import build_worker, connect, tls_from_secret
from .settings import agentcore_settings

app = BedrockAgentCoreApp()
log = app.logger
_worker_task: asyncio.Task[None] | None = None


async def _run(session_id: str) -> None:
    settings = agentcore_settings(os.environ)
    # The endpoint is named after the build, so the identity gives /kill its StopRuntimeSession qualifier.
    identity = agentcore_identity(settings.build_id, session_id)
    cert = TemporalCertSecret.model_validate_json(read_secret(os.environ["TEMPORAL_CERT_SECRET_ARN"]))
    client = await connect(settings, tls_from_secret(cert), identity, plugins(settings.app))
    tracker = ActivityTracker()
    worker = build_worker(client, settings, identity, interceptors=[tracker])
    log.info("polling %s as %s", settings.task_queue, identity)
    async with worker:
        await tracker.wait_until_idle(settings.drain_idle_seconds)
    log.info("idle for %ss: drained", settings.drain_idle_seconds)


async def _run_until_idle(task_id: int, session_id: str) -> None:
    try:
        await _run(session_id)
    except Exception:
        log.exception("worker failed")
    finally:
        # Without this, /ping stays HealthyBusy and the session is billed until its maximum lifetime.
        app.complete_async_task(task_id)


@app.entrypoint
async def invoke(payload: dict, context) -> dict:  # the SDK passes the context only to a parameter named `context`
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return {"message": "worker already polling"}
    session_id = getattr(context, "session_id", None) or "unknown"
    task_id = app.add_async_task("temporal-worker")
    _worker_task = asyncio.create_task(_run_until_idle(task_id, session_id))
    return {"message": "worker starting", "session": session_id}


def main() -> None:
    # Bind explicitly: the SDK only defaults to 0.0.0.0 when it detects Docker.
    app.run(host="0.0.0.0")


if __name__ == "__main__":
    main()

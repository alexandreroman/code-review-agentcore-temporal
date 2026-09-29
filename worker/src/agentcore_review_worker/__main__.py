"""Local dev worker: `python -m agentcore_review_worker` (make dev). Unversioned, on the dev task queue."""

import asyncio
import contextlib
import logging
import os
import signal
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import tracing
from .runtime import EXECUTOR_THREADS, build_worker, connect
from .settings import dev_settings

logger = logging.getLogger(__name__)


async def run() -> None:
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=EXECUTOR_THREADS))  # sized for the model calls
    settings = dev_settings(os.environ)
    identity = f"dev:{socket.gethostname()}"
    cert = Path(os.environ["TEMPORAL_TLS_CERT_PATH"]).read_bytes()
    key = Path(os.environ["TEMPORAL_TLS_KEY_PATH"]).read_bytes()
    client = await connect(settings, identity, cert, key)
    worker = build_worker(client, settings, identity)
    logger.info("polling %s on %s as %s", settings.task_queue, settings.namespace, identity)

    # A signal handler (not a bare KeyboardInterrupt) drives the worker's own graceful
    # shutdown, so Ctrl-C on stage stops it without a traceback or a dirty event loop.
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with worker:
        await stop.wait()
    tracing.flush()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()

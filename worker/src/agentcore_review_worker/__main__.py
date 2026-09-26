"""Local dev worker: `python -m agentcore_review_worker` (make dev). Unversioned, on the dev task queue."""

import asyncio
import logging
import os
import signal
import socket
import sys

from agentcore_review_shared.identity import dev_identity

from .registry import plugins
from .runtime import build_worker, connect, tls_from_files
from .settings import SettingsError, dev_settings

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = dev_settings(os.environ)
    identity = dev_identity(socket.gethostname())
    tls = tls_from_files(
        os.environ.get("TEMPORAL_TLS_CERT_PATH") or "certs/client.pem",
        os.environ.get("TEMPORAL_TLS_KEY_PATH") or "certs/client.key",
    )
    client = await connect(settings, tls, identity, plugins(settings.app))
    worker = build_worker(client, settings, identity)
    logger.info("polling %s on %s as %s", settings.task_queue, settings.namespace, identity)

    # A signal handler (not a bare KeyboardInterrupt) drives the worker's own graceful
    # shutdown, so Ctrl-C on stage stops it without a traceback or a dirty event loop.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with worker:
        await stop.wait()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except SettingsError as error:
        sys.exit(f"dev worker: {error}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

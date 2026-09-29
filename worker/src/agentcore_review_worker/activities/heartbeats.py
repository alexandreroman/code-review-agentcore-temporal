"""Heartbeats for every activity, under its 10 s heartbeat timeout (see workflows/policies.py).

The work runs in a thread or awaits I/O (a download, a sequence of GitHub calls), so the event loop stays free
to heartbeat every 5 s: an attempt cut off by a killed session is detected within one heartbeat timeout,
whatever the activity.
"""

import asyncio
import functools
from collections.abc import Awaitable, Callable

from temporalio import activity

HEARTBEAT_SECONDS = 5.0


def heartbeat_while_running[**P, T](fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Decorate an activity function (under @activity.defn) to heartbeat every HEARTBEAT_SECONDS while it runs."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        task = asyncio.ensure_future(fn(*args, **kwargs))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
                if done:
                    return task.result()
                activity.heartbeat()
        finally:
            # asyncio.wait leaves the task running when the activity is cancelled: stop it, or its writes go on
            # while the next attempt starts.
            task.cancel()

    return wrapper

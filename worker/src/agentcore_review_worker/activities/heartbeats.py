"""Heartbeats for activities whose work outlasts their heartbeat timeout (10 s, see workflows/policies.py).

The work runs in a thread or awaits I/O (a download, a sequence of GitHub calls), so the event loop stays free
to heartbeat every 5 s: an attempt cut off by a killed session is detected within one heartbeat timeout,
whatever the activity.
"""

import asyncio
import functools
from collections.abc import Awaitable, Callable

from temporalio import activity

HEARTBEAT_SECONDS = 5.0


async def heartbeating[T](work: Awaitable[T]) -> T:
    """Await `work` while heartbeating every HEARTBEAT_SECONDS."""
    task = asyncio.ensure_future(work)
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


def heartbeat_while_running[**P, T](fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """Decorate an activity function (under @activity.defn) so that its whole body runs in heartbeating().

    functools.wraps keeps the signature, type hints and docstring that @activity.defn reads the argument and
    return types from, and that activity_as_tool builds the tool's schema from.
    """

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await heartbeating(fn(*args, **kwargs))

    return wrapper

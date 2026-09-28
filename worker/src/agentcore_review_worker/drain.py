"""Tracks running activities so an AgentCore worker can drain once idle and release its session."""

import asyncio
from typing import Any

from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor


class ActivityTracker(Interceptor):
    """Counts the running activities: the worker drains once none has run for a while.

    Only activities count: workflow tasks are short, and Temporal redelivers one that a stopped worker left unfinished.
    """

    def __init__(self) -> None:
        self._inflight = 0
        self._changed = asyncio.Event()

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _TrackedActivities(next, self)

    def activity_started(self) -> None:
        self._inflight += 1
        self._changed.set()

    def activity_finished(self) -> None:
        self._inflight -= 1
        self._changed.set()

    async def wait_until_idle(self, idle_seconds: float) -> None:
        """Return once no activity has run or changed state for `idle_seconds`."""
        while True:
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=idle_seconds)
            except TimeoutError:
                if self._inflight == 0:
                    return


class _TrackedActivities(ActivityInboundInterceptor):
    def __init__(self, next: ActivityInboundInterceptor, tracker: ActivityTracker) -> None:
        super().__init__(next)
        self._tracker = tracker

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        self._tracker.activity_started()
        try:
            return await self.next.execute_activity(input)
        finally:
            self._tracker.activity_finished()

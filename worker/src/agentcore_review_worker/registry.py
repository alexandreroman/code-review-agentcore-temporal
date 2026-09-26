"""Everything the worker registers, shared by the entry points and the self-check."""

from collections.abc import Callable

from .activities.ping import PingActivities
from .workflows.ping import PingWorkflow

WORKFLOWS: list[type] = [PingWorkflow]


def activities(identity: str) -> list[Callable]:
    return [PingActivities(identity).ping]

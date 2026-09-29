"""Temporal calls made by the router: start or signal the pull request workflow, describe it, list pollers."""

import asyncio
from datetime import timedelta

from agentcore_review_shared.contract import PULL_REQUEST_WORKFLOW, SIGNAL_PR_UPDATED
from pydantic import BaseModel
from temporalio.api.enums.v1 import TaskQueueKind, TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from .routing import StartOrSignal

RPC_TIMEOUT = timedelta(seconds=5)


async def start_or_signal(client: Client, action: StartOrSignal) -> bool:
    """SignalWithStart(pr_updated). False when the reuse policy refuses a new run (a late event on a finished PR)."""
    try:
        await client.start_workflow(
            PULL_REQUEST_WORKFLOW,
            action.input,
            id=action.workflow_id,
            task_queue=action.task_queue,
            id_reuse_policy=action.reuse_policy,
            id_conflict_policy=action.conflict_policy,
            start_signal=SIGNAL_PR_UPDATED,
            start_signal_args=[action.signal],
            static_summary=action.summary,
            rpc_timeout=RPC_TIMEOUT,
        )
    except WorkflowAlreadyStartedError:
        return False
    except RPCError as error:
        # The SDK raises WorkflowAlreadyStartedError only when the server reply carries error details.
        if error.status == RPCStatusCode.ALREADY_EXISTS:
            return False
        raise
    return True


async def signal(client: Client, workflow_id: str, name: str, payload: BaseModel) -> bool:
    """Plain signal to the latest run. False when no workflow runs under this ID, or its latest run has ended."""
    try:
        await client.get_workflow_handle(workflow_id).signal(name, payload, rpc_timeout=RPC_TIMEOUT)
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    return True


async def workflow_task_queue(client: Client, workflow_id: str) -> str | None:
    """Task queue of the latest run, running or not; None when the PR never had a workflow."""
    try:
        description = await client.get_workflow_handle(workflow_id).describe(rpc_timeout=RPC_TIMEOUT)
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return None
        raise
    return description.task_queue


async def poller_identities(client: Client, task_queue: str) -> list[str]:
    """Identities polling the queue for workflow or activity tasks (the server keeps ~5 minutes of them)."""
    kinds = (TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW, TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY)
    responses = await asyncio.gather(
        *(
            client.workflow_service.describe_task_queue(
                DescribeTaskQueueRequest(
                    namespace=client.namespace,
                    task_queue=TaskQueue(name=task_queue, kind=TaskQueueKind.TASK_QUEUE_KIND_NORMAL),
                    task_queue_type=kind,
                ),
                timeout=RPC_TIMEOUT,
            )
            for kind in kinds
        )
    )
    return [poller.identity for response in responses for poller in response.pollers]

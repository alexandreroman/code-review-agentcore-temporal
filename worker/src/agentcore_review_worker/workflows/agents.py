"""Agent building blocks shared by the reviewer, synthesis, fixer and discussion workflows (workflow side).

A TemporalAgent runs the Strands loop inside the workflow: each model call is the plugin's activity,
each tool call is an activity (Glob, Grep, Read), and hooks run deterministically in workflow code.
Each tool activity's summary shows the call's arguments in Temporal UI (e.g. Read `app/main.py:1-400`).
"""

import copy
from collections.abc import Callable
from typing import Any, cast

from strands.hooks import BeforeModelCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.types.exceptions import (
    ContextWindowOverflowException,
    EventLoopException,
    MaxTokensReachedException,
    StructuredOutputException,
)
from strands.types.tools import AgentTool, ToolGenerator, ToolSpec, ToolUse
from temporalio import workflow
from temporalio.contrib.strands import TemporalAgent
from temporalio.contrib.strands.workflow import activity_as_tool
from temporalio.exceptions import ApplicationError

from agentcore_review_worker.workflows.policies import MODEL_ACTIVITY, TOOL_ACTIVITY

with workflow.unsafe.imports_passed_through():
    from pydantic import BaseModel

    from agentcore_review_worker import summaries
    from agentcore_review_worker.activities import tools as navigation_activities
    from agentcore_review_worker.limits import HARD_TURN_LIMIT, budget_message, tool_call_allowed
    from agentcore_review_worker.models import MODEL_NAME, SnapshotRef

AGENT_FAILURES: list[type[BaseException]] = [
    EventLoopException,
    StructuredOutputException,
    MaxTokensReachedException,
    ContextWindowOverflowException,
]
"""Raised by the Strands loop in workflow code. Listed in failure_exception_types, they fail the child workflow
instead of retrying its task forever. A failed model activity needs no entry: Strands re-raises it unwrapped,
and the raw ActivityError fails the workflow like any Temporal failure."""


class ModelCallBudget(HookProvider):
    """Counts model calls and cancels tool calls once the budget is spent, forcing the agent to conclude."""

    def __init__(self, output_tool: str) -> None:
        self._model_calls = 0
        self._output_tool = output_tool

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self._count)
        registry.add_callback(BeforeToolCallEvent, self._gate)

    def _count(self, event: BeforeModelCallEvent) -> None:
        self._model_calls += 1

    def _gate(self, event: BeforeToolCallEvent) -> None:
        if not tool_call_allowed(self._model_calls, event.tool_use["name"], self._output_tool):
            event.cancel_tool = budget_message(self._output_tool)


class _SnapshotBound(AgentTool):
    """A navigation activity shown to the model without its `snapshot` parameter, which the workflow fills in.

    activity_as_tool only takes a static summary: each call wraps the activity again, with a summary built
    from the model's arguments.
    """

    def __init__(self, activity_fn: Callable, snapshot: SnapshotRef) -> None:
        super().__init__()
        self._activity_fn = activity_fn
        self._tool = activity_as_tool(activity_fn, **TOOL_ACTIVITY)
        self._snapshot = snapshot.model_dump(mode="json")
        spec = copy.deepcopy(self._tool.tool_spec)
        schema = spec["inputSchema"]["json"]
        schema.pop("$defs", None)
        schema["properties"].pop("snapshot")
        schema["required"] = [name for name in schema.get("required", []) if name != "snapshot"]
        self._spec = spec

    @property
    def tool_name(self) -> str:
        return self._tool.tool_name

    @property
    def tool_spec(self) -> ToolSpec:
        return self._spec

    @property
    def tool_type(self) -> str:
        return self._tool.tool_type

    async def stream(self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any) -> ToolGenerator:
        summary = summaries.tool_call(self.tool_name, tool_use["input"])
        tool = activity_as_tool(self._activity_fn, **TOOL_ACTIVITY, summary=summary)
        bound = cast(ToolUse, {**tool_use, "input": {**tool_use["input"], "snapshot": self._snapshot}})
        async for event in tool.stream(bound, invocation_state, **kwargs):
            yield event


def navigation_tools(snapshot: SnapshotRef) -> list[AgentTool]:
    activities = (navigation_activities.glob, navigation_activities.grep, navigation_activities.read)
    return [_SnapshotBound(fn, snapshot) for fn in activities]


async def run_agent[T: BaseModel](
    *, name: str, system_prompt: str, tools: list[AgentTool], output: type[T], prompt: str | list[dict]
) -> T:
    """Run an agent to its structured output.

    A refusal ends the Strands loop without structured output: the agent is then unavailable, with a
    final error (reading the missing output would fail the workflow task forever instead).
    """
    agent = TemporalAgent(
        model=MODEL_NAME,
        summary=name,  # labels the model activities in Temporal UI
        **MODEL_ACTIVITY,
        system_prompt=system_prompt,
        tools=tools,
        structured_output_model=output,
        hooks=[ModelCallBudget(output.__name__)],
        callback_handler=None,  # no printing from workflow code
    )
    result = await agent.invoke_async(prompt, limits={"turns": HARD_TURN_LIMIT})
    if result.structured_output is None:
        raise ApplicationError(
            f"{name} unavailable: no structured output (stop reason {result.stop_reason})",
            type="AgentUnavailable",
            non_retryable=True,
        )
    return cast(T, result.structured_output)

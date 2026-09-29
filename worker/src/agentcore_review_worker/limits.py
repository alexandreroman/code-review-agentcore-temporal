"""The agents' model call budget: a call often takes 60-80 s, and an agent's calls must fit CHILD_RUN_TIMEOUT."""

MAX_MODEL_CALLS = 8
HARD_TURN_LIMIT = MAX_MODEL_CALLS + 3
"""Strands turn cap: a backstop for a model that keeps calling tools after being told to stop."""


def tool_call_allowed(model_calls: int, tool_name: str, output_tool: str) -> bool:
    """Tool calls stop running once the agent has made MAX_MODEL_CALLS model calls.

    The structured-output tool always runs: calling it is how the agent concludes.
    """
    return tool_name == output_tool or model_calls < MAX_MODEL_CALLS


def budget_message(output_tool: str) -> str:
    return (
        f"Tool budget exhausted ({MAX_MODEL_CALLS} model calls): this tool call was not executed. "
        f"Do not call Glob, Grep or Read again; submit your answer now with the {output_tool} tool."
    )

"""The agents' model call budgets: a call often takes 5-60 s, and an agent's calls must fit CHILD_RUN_TIMEOUT."""

MAX_MODEL_CALLS = 8
"""The default budget: reviewers, synthesis and discussion."""

FIXER_MODEL_CALLS = 12
"""The fixer reads more files than a reviewer (every file it changes, and the types it uses) before writing."""


def tool_call_allowed(model_calls: int, tool_name: str, output_tool: str, max_calls: int) -> bool:
    """Tool calls stop running once the agent has made max_calls model calls.

    The structured-output tool always runs: calling it is how the agent concludes.
    """
    return tool_name == output_tool or model_calls < max_calls


def budget_message(output_tool: str, max_calls: int) -> str:
    return (
        f"Tool budget exhausted ({max_calls} model calls): this tool call was not executed. "
        f"Do not call Glob, Grep or Read again; submit your answer now with the {output_tool} tool."
    )

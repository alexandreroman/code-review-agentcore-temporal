from agentcore_review_worker.limits import HARD_TURN_LIMIT, MAX_MODEL_CALLS, budget_message, tool_call_allowed


def test_tools_run_until_the_budget_is_spent():
    assert all(tool_call_allowed(calls, "Grep", "ReviewerReport") for calls in range(1, MAX_MODEL_CALLS))
    assert not tool_call_allowed(MAX_MODEL_CALLS, "Grep", "ReviewerReport")


def test_the_output_tool_always_runs():
    assert tool_call_allowed(MAX_MODEL_CALLS + 5, "ReviewerReport", "ReviewerReport")


def test_budget_message_names_the_output_tool():
    assert "FixPlan" in budget_message("FixPlan")


def test_the_hard_limit_leaves_room_to_conclude():
    assert MAX_MODEL_CALLS == 8 and HARD_TURN_LIMIT > MAX_MODEL_CALLS + 1

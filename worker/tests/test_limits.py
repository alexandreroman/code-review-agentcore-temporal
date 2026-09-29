from agentcore_review_worker.limits import tool_call_allowed


def test_tools_run_until_the_budget_is_spent():
    assert all(tool_call_allowed(calls, "Grep", "ReviewerReport", max_calls=12) for calls in range(1, 12))
    assert not tool_call_allowed(12, "Grep", "ReviewerReport", max_calls=12)


def test_the_output_tool_always_runs():
    assert tool_call_allowed(12 + 5, "ReviewerReport", "ReviewerReport", max_calls=12)

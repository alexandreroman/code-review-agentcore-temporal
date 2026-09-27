"""DiscussionWorkflow: an agent answers a human reply in a finding's review thread, and may dismiss the finding.

The parent posts the answer and applies the verdict: this child only reads the repository.
"""

from temporalio import workflow

from agentcore_review_worker.workflows.agents import AGENT_FAILURES, navigation_tools, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_worker import prompts
    from agentcore_review_worker.models import DiscussionInput, DiscussionReply


@workflow.defn(name="DiscussionWorkflow", failure_exception_types=AGENT_FAILURES)
class DiscussionWorkflow:
    @workflow.run
    async def run(self, input: DiscussionInput) -> DiscussionReply:
        return await run_agent(
            name="discussion",
            system_prompt=prompts.DISCUSSION_SYSTEM,
            tools=navigation_tools(input.snapshot),
            output=DiscussionReply,
            prompt=prompts.discussion_prompt(input.finding, input.thread, input.author),
        )

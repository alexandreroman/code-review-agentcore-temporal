"""ConversationWorkflow: an agent answers a comment in the pull request's Conversation, about the repository's code
and the pull request only.

The parent decides what to post from the reply: this child only reads the repository, and has no verdict to give.
"""

from temporalio import workflow

from agentcore_review_worker.workflows.agents import AGENT_FAILURES, navigation_tools, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import CONVERSATION_WORKFLOW

    from agentcore_review_worker import prompts
    from agentcore_review_worker.models import ConversationInput, ConversationReply


@workflow.defn(name=CONVERSATION_WORKFLOW, failure_exception_types=AGENT_FAILURES)
class ConversationWorkflow:
    @workflow.run
    async def run(self, input: ConversationInput) -> ConversationReply:
        return await run_agent(
            name="conversation",
            system_prompt=prompts.CONVERSATION_SYSTEM,
            tools=navigation_tools(input.snapshot),
            output=ConversationReply,
            prompt=prompts.conversation_prompt(input),
        )

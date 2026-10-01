"""SynthesisWorkflow: deduplicates a round's findings and writes its summary (no tools)."""

from temporalio import workflow

from agentcore_review_worker.workflows.agents import AGENT_FAILURES, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import SYNTHESIS_WORKFLOW

    from agentcore_review_worker import prompts
    from agentcore_review_worker.models import ReviewSummary, SynthesisInput


@workflow.defn(name=SYNTHESIS_WORKFLOW, failure_exception_types=AGENT_FAILURES)
class SynthesisWorkflow:
    @workflow.run
    async def run(self, input: SynthesisInput) -> ReviewSummary:
        return await run_agent(
            name="synthesis",
            system_prompt=prompts.SYNTHESIS_SYSTEM,
            tools=[],
            output=ReviewSummary,
            prompt=prompts.synthesis_prompt(input),
        )

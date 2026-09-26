"""SynthesisWorkflow: deduplicates and orders a round's findings and writes its summary (no tools)."""

from temporalio import workflow

from agentcore_review_worker.workflows.agents import AGENT_FAILURES, new_agent, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import ReviewSummary

    from agentcore_review_worker import prompts
    from agentcore_review_worker.models import SynthesisInput


@workflow.defn(name="SynthesisWorkflow", failure_exception_types=AGENT_FAILURES)
class SynthesisWorkflow:
    @workflow.run
    async def run(self, input: SynthesisInput) -> ReviewSummary:
        agent = new_agent(system_prompt=prompts.SYNTHESIS_SYSTEM, output=ReviewSummary, tools=[], summary="synthesis")
        return await run_agent(agent, prompts.synthesis_prompt(input), ReviewSummary, "synthesis")

"""ReviewerWorkflow: one specialized reviewer (security, performance or maintainability) on one batch of files."""

from temporalio import workflow

from agentcore_review_worker.workflows import policies
from agentcore_review_worker.workflows.agents import AGENT_FAILURES, navigation_tools, new_agent, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import ReviewerReport

    from agentcore_review_worker import prompts
    from agentcore_review_worker.lifecycle import clean_report
    from agentcore_review_worker.models import BatchPatches, ReviewerInput


@workflow.defn(name="ReviewerWorkflow", failure_exception_types=AGENT_FAILURES)
class ReviewerWorkflow:
    @workflow.run
    async def run(self, input: ReviewerInput) -> ReviewerReport:
        # The batch's patches go into the first prompt; the tools only add context from the snapshot.
        patches = await workflow.execute_activity(
            "fetch_batch_patches", input.batch, result_type=BatchPatches, **policies.FETCH_BATCH_PATCHES
        )
        name = f"{input.category} reviewer"
        agent = new_agent(
            system_prompt=prompts.REVIEWER_SYSTEM,
            output=ReviewerReport,
            tools=navigation_tools(input.snapshot),
            summary=name,
        )
        prompt = prompts.reviewer_prompt(input.category, patches, input.open_findings)
        report = await run_agent(agent, prompt, ReviewerReport, name)
        return clean_report(report, input.category, [f.id for f in input.open_findings])

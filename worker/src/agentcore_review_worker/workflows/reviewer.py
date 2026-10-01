"""ReviewerWorkflow: one specialized reviewer (security, performance or maintainability) on one batch of files."""

from temporalio import workflow

from agentcore_review_worker.workflows import policies
from agentcore_review_worker.workflows.agents import AGENT_FAILURES, navigation_tools, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import REVIEWER_WORKFLOW

    from agentcore_review_worker import prompts, summaries
    from agentcore_review_worker.lifecycle import clean_report
    from agentcore_review_worker.models import BatchPatches, ReviewerInput, ReviewerReport


@workflow.defn(name=REVIEWER_WORKFLOW, failure_exception_types=AGENT_FAILURES)
class ReviewerWorkflow:
    @workflow.run
    async def run(self, input: ReviewerInput) -> ReviewerReport:
        # The batch's patches go into the first prompt; the tools only add context from the snapshot.
        patches = await workflow.execute_activity(
            "FetchDiff",
            input.batch,
            result_type=BatchPatches,
            summary=summaries.diff_files(input.batch.paths),
            **policies.GITHUB_CALL,
        )
        report = await run_agent(
            name=f"{input.category} reviewer",
            system_prompt=prompts.REVIEWER_SYSTEM,
            tools=navigation_tools(input.snapshot),
            output=ReviewerReport,
            prompt=prompts.reviewer_prompt(
                input.category, patches, input.open_findings, input.dismissed_findings, input.fix_round
            ),
        )
        cleaned = clean_report(report, input.category, [f.id for f in input.open_findings], input.fix_round)
        dropped = len(report.findings) - len(cleaned.findings)
        if dropped:
            workflow.logger.info(
                "%s reviewer: %d finding(s) below high dropped in a fix round", input.category, dropped
            )
        return cleaned

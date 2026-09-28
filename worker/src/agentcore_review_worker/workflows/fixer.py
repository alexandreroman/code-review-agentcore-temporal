"""FixerWorkflow: an agent writes the fix, then CommitFix pushes it as one commit.

The commit runs here rather than in the parent: a FixPlan holds whole files, and the parent's history
only carries metadata. The parent gets the commit SHA back.
"""

from temporalio import workflow

from agentcore_review_worker.workflows import policies
from agentcore_review_worker.workflows.agents import AGENT_FAILURES, navigation_tools, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_worker import prompts, summaries
    from agentcore_review_worker.models import CommitInput, CommitResult, FixerInput, FixPlan


@workflow.defn(name="FixerWorkflow", failure_exception_types=AGENT_FAILURES)
class FixerWorkflow:
    @workflow.run
    async def run(self, input: FixerInput) -> CommitResult:
        plan = await run_agent(
            name="fixer",
            system_prompt=prompts.FIXER_SYSTEM,
            tools=navigation_tools(input.snapshot),
            output=FixPlan,
            prompt=prompts.fixer_prompt(input.findings),
        )
        commit = CommitInput(
            pr=input.pr,
            workflow_id=input.workflow_id,
            fix_number=input.fix_number,
            expected_head_sha=input.expected_head_sha,
            plan=plan,
        )
        return await workflow.execute_activity(
            "CommitFix",
            commit,
            result_type=CommitResult,
            summary=summaries.commit(input.fix_number, len(plan.changes)),
            **policies.COMMIT_FIX,
        )

"""FixerWorkflow: an agent writes the fix, then commit_changes pushes it as one commit.

The commit runs here rather than in the parent: a FixPlan holds whole files, and the parent's history
only carries metadata. The parent gets the commit SHA back.
"""

from temporalio import workflow
from temporalio.exceptions import ApplicationError

from agentcore_review_worker.workflows import policies
from agentcore_review_worker.workflows.agents import AGENT_FAILURES, navigation_tools, new_agent, run_agent

with workflow.unsafe.imports_passed_through():
    from agentcore_review_shared.contract import FixPlan

    from agentcore_review_worker import prompts
    from agentcore_review_worker.models import CommitInput, CommitResult, FixerInput


@workflow.defn(name="FixerWorkflow", failure_exception_types=AGENT_FAILURES)
class FixerWorkflow:
    @workflow.run
    async def run(self, input: FixerInput) -> CommitResult:
        agent = new_agent(
            system_prompt=prompts.FIXER_SYSTEM, output=FixPlan, tools=navigation_tools(input.snapshot), summary="fixer"
        )
        plan = await run_agent(agent, prompts.fixer_prompt(input.findings), FixPlan, "fixer")
        if not plan.changes:
            raise ApplicationError("the fixer proposed no change", type="EmptyFixPlan", non_retryable=True)
        commit = CommitInput(
            pr=input.pr,
            workflow_id=input.workflow_id,
            fix_number=input.fix_number,
            expected_head_sha=input.expected_head_sha,
            plan=plan,
        )
        return await workflow.execute_activity(
            "commit_changes", commit, result_type=CommitResult, **policies.COMMIT_CHANGES
        )

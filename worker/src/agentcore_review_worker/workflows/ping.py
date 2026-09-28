"""Ping: proves that a worker picks up the task queue (make ping)."""

from temporalio import workflow

from agentcore_review_worker.workflows import policies

with workflow.unsafe.imports_passed_through():
    from agentcore_review_worker import summaries


@workflow.defn(name="Ping")
class PingWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        return await workflow.execute_activity(
            "Ping",
            message,
            result_type=str,
            summary=summaries.fit(message),
            **policies.PING,
        )

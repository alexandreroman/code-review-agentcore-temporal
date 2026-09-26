"""Ping: proves that a worker picks up the task queue (make ping, deploy checks)."""

from datetime import timedelta

from temporalio import workflow


@workflow.defn(name="Ping")
class PingWorkflow:
    @workflow.run
    async def run(self, message: str) -> str:
        # Called by name so this module never imports the activity module.
        return await workflow.execute_activity(
            "ping", message, start_to_close_timeout=timedelta(seconds=30), result_type=str
        )

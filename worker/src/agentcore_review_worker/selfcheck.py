"""Pre-deploy check, run inside the built image: imports and sandbox validation of every workflow.

A workflow module that imports an I/O library fails this validation when the worker starts. On AgentCore that
crash also prevents the task queue from attaching to the version, so it must be caught before pushing.
"""

import asyncio

import temporalio.workflow
from temporalio.worker import WorkerConfig
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from .registry import WORKFLOWS, activities, plugins
from .settings import AppSettings

# Placeholder settings: everything is built without reading a secret or calling AWS.
SELFCHECK = AppSettings(
    snapshots_bucket="selfcheck",
    github_app_secret="selfcheck",
    anthropic_secret="selfcheck",
    anthropic_model="selfcheck",
    anthropic_effort="high",
    max_parallel_agents=1,
)


def validate_workflows() -> list[str]:
    # Sandbox instance creation needs a running event loop (it initializes the workflow's asyncio
    # runtime), which the real Worker has while it starts. This standalone check has none of its own.
    return asyncio.run(_validate_workflows())


async def _validate_workflows() -> list[str]:
    # The Worker applies its plugins' sandbox settings (Strands passthrough); validate with the same ones.
    config = WorkerConfig(workflow_runner=SandboxedWorkflowRunner())
    for plugin in plugins(SELFCHECK):
        config = plugin.configure_worker(config)
    runner = config["workflow_runner"]
    names = []
    for cls in WORKFLOWS:
        # The same (private) definition lookup and validation the Worker runs at startup.
        definition = temporalio.workflow._Definition.must_from_class(cls)
        runner.prepare_workflow(definition)
        names.append(definition.name)
    return names


def main() -> None:
    names = validate_workflows()
    activities(SELFCHECK, "selfcheck")
    print(f"selfcheck ok: {', '.join(names)}")


if __name__ == "__main__":
    main()

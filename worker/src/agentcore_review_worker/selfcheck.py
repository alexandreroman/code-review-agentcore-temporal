"""Pre-deploy check, run inside the built image: imports and sandbox validation of every workflow.

A workflow module that imports an I/O library fails this validation when the worker starts. On AgentCore that
crash also prevents the task queue from attaching to the version, so it must be caught before pushing.
"""

import asyncio

import temporalio.workflow
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from .registry import WORKFLOWS, activities


def validate_workflows() -> list[str]:
    # Sandbox instance creation needs a running event loop (it initializes the workflow's asyncio
    # runtime), which the real Worker has while it starts. This standalone check has none of its own.
    return asyncio.run(_validate_workflows())


async def _validate_workflows() -> list[str]:
    runner = SandboxedWorkflowRunner()
    names = []
    for cls in WORKFLOWS:
        # The same (private) definition lookup and validation the Worker runs at startup.
        definition = temporalio.workflow._Definition.must_from_class(cls)
        runner.prepare_workflow(definition)
        names.append(definition.name)
    return names


def main() -> None:
    names = validate_workflows()
    activities("selfcheck")
    print(f"selfcheck ok: {', '.join(names)}")


if __name__ == "__main__":
    main()

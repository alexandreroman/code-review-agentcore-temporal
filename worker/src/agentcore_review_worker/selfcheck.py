"""Pre-deploy check, run inside the built image: imports and sandbox validation of every workflow, tracing off and on.

A workflow module that imports an I/O library fails this validation when the worker starts. On AgentCore that
crash also prevents the task queue from attaching to the version, so it must be caught before pushing.
"""

import asyncio

import boto3
import temporalio.workflow
from temporalio.worker import ReplayerConfig
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from . import tracing
from .runtime import WORKFLOWS, plugins
from .settings import AppSettings

# Placeholder settings: everything is built without reading a secret or calling AWS.
SELFCHECK = AppSettings(
    snapshots_bucket="selfcheck",
    github_app_secret="selfcheck",
    workload_identity="selfcheck",
    anthropic_credential_provider="selfcheck",
    anthropic_model="selfcheck",
    anthropic_effort="selfcheck",
    max_parallel_agents=1,
)


async def validate_workflows(with_tracing: bool) -> list[str]:
    # The Worker applies its plugins' sandbox settings (Strands and OpenTelemetry passthroughs); validate with the same.
    # configure_replayer applies them as configure_worker does, without the client that one reads interceptors from.
    config = ReplayerConfig(workflow_runner=SandboxedWorkflowRunner())
    for plugin in plugins(SELFCHECK, with_tracing=with_tracing):
        config = plugin.configure_replayer(config)
    runner = config["workflow_runner"]
    names = []
    for cls in WORKFLOWS:
        # The same (private) definition lookup and validation the Worker runs at startup.
        definition = temporalio.workflow._Definition.must_from_class(cls)
        runner.prepare_workflow(definition)
        names.append(definition.name)
    return names


def main() -> None:
    # Sandbox instance creation needs a running event loop (it initializes the workflow's asyncio
    # runtime), which the real Worker has while it starts. This standalone check has none of its own.
    asyncio.run(validate_workflows(with_tracing=False))
    names = asyncio.run(validate_workflows(with_tracing=True))
    # The exporter, as TRACING=on builds it (requests session, SigV4 signer): nothing is sent.
    tracing.create_provider(boto3.Session(region_name="us-east-1"), "selfcheck", None).shutdown()
    print(f"selfcheck ok, tracing off and on: {', '.join(names)}")


if __name__ == "__main__":
    main()

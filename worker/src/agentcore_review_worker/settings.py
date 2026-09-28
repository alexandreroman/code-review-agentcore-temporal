"""Worker settings, read from the environment: AgentCore runtime variables, or the local .env via make.

Settings hold where secrets live (Secrets Manager ARNs or names, AgentCore Identity names), never their values.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from agentcore_review_shared.secrets import (
    ANTHROPIC_CREDENTIAL_PROVIDER,
    GITHUB_APP_SECRET,
    WORKER_WORKLOAD_IDENTITY,
)
from temporalio.worker import WorkerDeploymentVersion


@dataclass(frozen=True)
class AppSettings:
    """What the activities and the model factory need."""

    snapshots_bucket: str
    github_app_secret: str  # Secrets Manager ARN or name
    workload_identity: str  # AgentCore Identity workload identity name
    anthropic_credential_provider: str  # AgentCore Identity API key credential provider name
    anthropic_model: str
    anthropic_effort: str
    max_parallel_agents: int


@dataclass(frozen=True)
class WorkerSettings:
    address: str
    namespace: str
    task_queue: str
    deployment: WorkerDeploymentVersion | None  # None for the unversioned dev worker
    tracing: bool  # TRACING=on: spans exported to CloudWatch
    app: AppSettings


def agentcore_settings(env: Mapping[str, str]) -> WorkerSettings:
    return WorkerSettings(
        address=env["TEMPORAL_ADDRESS"],
        namespace=env["TEMPORAL_NAMESPACE"],
        task_queue=env["TASK_QUEUE"],
        deployment=WorkerDeploymentVersion(
            deployment_name=env["TEMPORAL_DEPLOYMENT_NAME"], build_id=env["TEMPORAL_BUILD_ID"]
        ),
        tracing=_tracing(env),
        app=_app_settings(
            env,
            github_app_secret=env["GITHUB_APP_SECRET_ID"],
            workload_identity=env["WORKLOAD_IDENTITY_NAME"],
            anthropic_credential_provider=env["ANTHROPIC_CREDENTIAL_PROVIDER"],
        ),
    )


def dev_settings(env: Mapping[str, str]) -> WorkerSettings:
    return WorkerSettings(
        address=env["TEMPORAL_ADDRESS"],
        namespace=env["TEMPORAL_NAMESPACE"],
        task_queue=env["DEV_TASK_QUEUE"],
        deployment=None,
        tracing=_tracing(env),
        # The dev worker reads the same secrets by name, with the developer's AWS credentials.
        app=_app_settings(
            env,
            github_app_secret=GITHUB_APP_SECRET,
            workload_identity=WORKER_WORKLOAD_IDENTITY,
            anthropic_credential_provider=ANTHROPIC_CREDENTIAL_PROVIDER,
        ),
    )


def _tracing(env: Mapping[str, str]) -> bool:
    value = env.get("TRACING", "off")
    if value not in ("on", "off"):
        raise ValueError(f"TRACING must be on or off, not {value!r}")
    return value == "on"


def _app_settings(
    env: Mapping[str, str], *, github_app_secret: str, workload_identity: str, anthropic_credential_provider: str
) -> AppSettings:
    return AppSettings(
        snapshots_bucket=env["SNAPSHOTS_BUCKET"],
        github_app_secret=github_app_secret,
        workload_identity=workload_identity,
        anthropic_credential_provider=anthropic_credential_provider,
        anthropic_model=env["ANTHROPIC_MODEL"],
        anthropic_effort=env["ANTHROPIC_EFFORT"],
        max_parallel_agents=int(env["MAX_PARALLEL_AGENTS"]),
    )

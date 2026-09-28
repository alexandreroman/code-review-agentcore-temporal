"""Worker settings, read from the environment: AgentCore runtime variables, or the local .env via make.

Settings hold where secrets live (Secrets Manager ARNs or names), never their values.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from agentcore_review_shared.secrets import ANTHROPIC_SECRET, GITHUB_APP_SECRET
from temporalio.worker import WorkerDeploymentVersion


@dataclass(frozen=True)
class AppSettings:
    """What the activities and the model factory need."""

    snapshots_bucket: str
    github_app_secret: str  # Secrets Manager ARN or name
    anthropic_secret: str  # Secrets Manager ARN or name
    anthropic_model: str
    anthropic_effort: str
    max_parallel_agents: int


@dataclass(frozen=True)
class WorkerSettings:
    address: str
    namespace: str
    task_queue: str
    deployment: WorkerDeploymentVersion | None  # None for the unversioned dev worker
    app: AppSettings


def agentcore_settings(env: Mapping[str, str]) -> WorkerSettings:
    return WorkerSettings(
        address=env["TEMPORAL_ADDRESS"],
        namespace=env["TEMPORAL_NAMESPACE"],
        task_queue=env["TASK_QUEUE"],
        deployment=WorkerDeploymentVersion(
            deployment_name=env["TEMPORAL_DEPLOYMENT_NAME"], build_id=env["TEMPORAL_BUILD_ID"]
        ),
        app=_app_settings(
            env,
            github_app_secret=env["GITHUB_APP_SECRET_ID"],
            anthropic_secret=env["ANTHROPIC_SECRET_ARN"],
        ),
    )


def dev_settings(env: Mapping[str, str]) -> WorkerSettings:
    return WorkerSettings(
        address=env["TEMPORAL_ADDRESS"],
        namespace=env["TEMPORAL_NAMESPACE"],
        task_queue=env["DEV_TASK_QUEUE"],
        deployment=None,
        # The dev worker reads the same secrets by name, with the developer's AWS credentials.
        app=_app_settings(env, github_app_secret=GITHUB_APP_SECRET, anthropic_secret=ANTHROPIC_SECRET),
    )


def _app_settings(env: Mapping[str, str], *, github_app_secret: str, anthropic_secret: str) -> AppSettings:
    return AppSettings(
        snapshots_bucket=env["SNAPSHOTS_BUCKET"],
        github_app_secret=github_app_secret,
        anthropic_secret=anthropic_secret,
        anthropic_model=env["ANTHROPIC_MODEL"],
        anthropic_effort=env["ANTHROPIC_EFFORT"],
        max_parallel_agents=int(env["MAX_PARALLEL_AGENTS"]),
    )

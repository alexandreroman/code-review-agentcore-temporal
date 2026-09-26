"""Worker settings, read from the environment: AgentCore runtime variables, or the local .env via make.

Settings hold where secrets live (ARNs on AgentCore, names in dev), never their values.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from agentcore_review_shared.secrets import ANTHROPIC_SECRET, GITHUB_APP_SECRET

NAMESPACE_PLACEHOLDER = "your-namespace.a1b2c"
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_PARALLEL_AGENTS = 3


class SettingsError(ValueError):
    """A required setting is missing or invalid."""


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
    deployment_name: str | None  # None for the unversioned dev worker
    build_id: str | None
    drain_idle_seconds: float
    app: AppSettings

    @property
    def versioned(self) -> bool:
        return self.build_id is not None


def agentcore_settings(env: Mapping[str, str]) -> WorkerSettings:
    return WorkerSettings(
        address=_required(env, "TEMPORAL_ADDRESS"),
        namespace=_required(env, "TEMPORAL_NAMESPACE"),
        task_queue=_required(env, "TASK_QUEUE"),
        deployment_name=_required(env, "TEMPORAL_DEPLOYMENT_NAME"),
        build_id=_required(env, "TEMPORAL_BUILD_ID"),
        drain_idle_seconds=float(env.get("DRAIN_IDLE_SECONDS") or 60),
        app=_app_settings(
            env,
            github_app_secret=_required(env, "GITHUB_APP_SECRET_ARN"),
            anthropic_secret=_required(env, "ANTHROPIC_SECRET_ARN"),
        ),
    )


def dev_settings(env: Mapping[str, str]) -> WorkerSettings:
    namespace = _required(env, "TEMPORAL_NAMESPACE")
    if namespace == NAMESPACE_PLACEHOLDER:
        raise SettingsError("TEMPORAL_NAMESPACE still holds the .env.example placeholder")
    return WorkerSettings(
        address=env.get("TEMPORAL_ADDRESS") or f"{namespace}.tmprl.cloud:7233",
        namespace=namespace,
        task_queue=env.get("DEV_TASK_QUEUE") or "review-dev",
        deployment_name=None,
        build_id=None,
        drain_idle_seconds=0,
        # The dev worker reads the same secrets by name, with the developer's AWS credentials.
        app=_app_settings(
            env,
            github_app_secret=env.get("GITHUB_APP_SECRET_ARN") or GITHUB_APP_SECRET,
            anthropic_secret=env.get("ANTHROPIC_SECRET_ARN") or ANTHROPIC_SECRET,
        ),
    )


def _app_settings(env: Mapping[str, str], *, github_app_secret: str, anthropic_secret: str) -> AppSettings:
    return AppSettings(
        snapshots_bucket=_required(env, "SNAPSHOTS_BUCKET"),
        github_app_secret=github_app_secret,
        anthropic_secret=anthropic_secret,
        anthropic_model=env.get("ANTHROPIC_MODEL") or DEFAULT_MODEL,
        anthropic_effort=env.get("ANTHROPIC_EFFORT") or DEFAULT_EFFORT,
        max_parallel_agents=_positive_int(env, "MAX_PARALLEL_AGENTS", DEFAULT_MAX_PARALLEL_AGENTS),
    )


def _required(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise SettingsError(f"{name} is not set")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be an integer, got {raw!r}") from None
    if value < 1:
        raise SettingsError(f"{name} must be at least 1, got {value}")
    return value

"""Worker settings, read from the environment: AgentCore runtime variables, or the local .env via make."""

from collections.abc import Mapping
from dataclasses import dataclass

NAMESPACE_PLACEHOLDER = "your-namespace.a1b2c"


class SettingsError(ValueError):
    """A required setting is missing."""


@dataclass(frozen=True)
class WorkerSettings:
    address: str
    namespace: str
    task_queue: str
    deployment_name: str | None  # None for the unversioned dev worker
    build_id: str | None
    drain_idle_seconds: float

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
    )


def _required(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise SettingsError(f"{name} is not set")
    return value

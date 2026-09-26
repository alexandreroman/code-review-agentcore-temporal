"""Temporal client and worker construction, shared by the local and AgentCore entry points."""

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from agentcore_review_shared.secrets import TemporalCertSecret
from temporalio.client import Client, Plugin
from temporalio.common import VersioningBehavior
from temporalio.service import TLSConfig
from temporalio.worker import Interceptor, Worker, WorkerDeploymentConfig, WorkerDeploymentVersion

from .registry import WORKFLOWS, activities
from .settings import WorkerSettings


def tls_from_files(cert_path: str, key_path: str) -> TLSConfig:
    return TLSConfig(client_cert=Path(cert_path).read_bytes(), client_private_key=Path(key_path).read_bytes())


def tls_from_secret(secret: TemporalCertSecret) -> TLSConfig:
    return TLSConfig(client_cert=secret.cert.encode(), client_private_key=secret.key.encode())


async def connect(settings: WorkerSettings, tls: TLSConfig, identity: str, plugins: Sequence[Plugin] = ()) -> Client:
    # No explicit data converter: StrandsPlugin installs the Pydantic converter with its failure converter
    # (Strands errors stay typed and non-retryable), and only does so over the default converter.
    return await Client.connect(
        settings.address, namespace=settings.namespace, tls=tls, identity=identity, plugins=list(plugins)
    )


def build_worker(
    client: Client, settings: WorkerSettings, identity: str, interceptors: Sequence[Interceptor] = ()
) -> Worker:
    deployment = None
    if settings.versioned:
        deployment = WorkerDeploymentConfig(
            version=WorkerDeploymentVersion(deployment_name=settings.deployment_name, build_id=settings.build_id),
            use_worker_versioning=True,
            default_versioning_behavior=VersioningBehavior.PINNED,
        )
    # The dev worker's Ctrl-C stands in for AgentCore's /kill: it must cancel activities at once,
    # like a crash, so the same run resumes at attempt 2 when a worker comes back. The AgentCore
    # worker keeps a full drain instead: its idle-session teardown (ActivityTracker) depends on it.
    graceful_shutdown_timeout = timedelta(seconds=120) if settings.versioned else timedelta(0)
    return Worker(
        client,
        task_queue=settings.task_queue,
        workflows=WORKFLOWS,
        activities=activities(settings.app, identity),
        interceptors=list(interceptors),
        identity=identity,
        deployment_config=deployment,
        graceful_shutdown_timeout=graceful_shutdown_timeout,
    )

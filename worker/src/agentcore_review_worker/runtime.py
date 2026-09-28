"""How the worker is assembled: its workflows, activities and Temporal client, shared by every entry point."""

from collections.abc import Callable, Sequence
from datetime import timedelta

from temporalio.client import Client
from temporalio.common import VersioningBehavior
from temporalio.service import TLSConfig
from temporalio.worker import Interceptor, Worker, WorkerDeploymentConfig, WorkerDeploymentVersion

from .activities import commits, github_api, reviews, tools
from .activities.ping import PingActivities
from .activities.pulls import PullActivities
from .activities.snapshots import SnapshotActivities
from .agent_model import strands_plugin
from .settings import AppSettings, WorkerSettings
from .workflows.discussion import DiscussionWorkflow
from .workflows.fixer import FixerWorkflow
from .workflows.ping import PingWorkflow
from .workflows.pull_request import PullRequestWorkflow
from .workflows.reviewer import ReviewerWorkflow
from .workflows.synthesis import SynthesisWorkflow

WORKFLOWS: list[type] = [
    PingWorkflow,
    PullRequestWorkflow,
    ReviewerWorkflow,
    SynthesisWorkflow,
    FixerWorkflow,
    DiscussionWorkflow,
]


def activities(settings: AppSettings, identity: str) -> list[Callable]:
    github_api.configure(settings.github_app_secret)
    pulls = PullActivities(settings)
    snapshots = SnapshotActivities(settings)
    return [
        PingActivities(identity).ping,
        pulls.list_changed_files,
        pulls.fetch_batch_patches,
        snapshots.snapshot_repo,
        snapshots.delete_snapshots,
        reviews.set_check,
        reviews.publish_review,
        reviews.resolve_threads,
        reviews.read_thread,
        reviews.post_thread_reply,
        reviews.post_pr_comment,
        reviews.close_pull_request,
        commits.commit_changes,
        tools.glob_tool,
        tools.grep_tool,
        tools.read_tool,
    ]


async def connect(settings: WorkerSettings, identity: str, cert: bytes, key: bytes) -> Client:
    # The Worker inherits the client's plugins: the Strands model activities, sandbox passthrough and converter.
    # No explicit data converter: StrandsPlugin installs the Pydantic converter with its failure converter
    # (Strands errors stay typed and non-retryable), and only does so over the default converter.
    return await Client.connect(
        settings.address,
        namespace=settings.namespace,
        tls=TLSConfig(client_cert=cert, client_private_key=key),
        identity=identity,
        plugins=[strands_plugin(settings.app)],
    )


def build_worker(
    client: Client, settings: WorkerSettings, identity: str, interceptors: Sequence[Interceptor] = ()
) -> Worker:
    deployment = None
    if settings.deployment_name is not None and settings.build_id is not None:
        deployment = WorkerDeploymentConfig(
            version=WorkerDeploymentVersion(deployment_name=settings.deployment_name, build_id=settings.build_id),
            use_worker_versioning=True,
            default_versioning_behavior=VersioningBehavior.PINNED,
        )
    # The dev worker's Ctrl-C stands in for AgentCore's /kill: it must cancel activities at once,
    # like a crash, so the same run resumes at attempt 2 when a worker comes back. The AgentCore
    # worker keeps a normal graceful shutdown: it stops only once idle, so there is rarely anything to finish.
    graceful_shutdown_timeout = timedelta(seconds=120) if deployment is not None else timedelta(0)
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

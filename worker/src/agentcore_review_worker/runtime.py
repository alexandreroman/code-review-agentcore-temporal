"""How the worker is assembled: its workflows, activities and Temporal client, shared by every entry point."""

from collections.abc import Callable, Sequence
from datetime import timedelta

from temporalio.client import Client
from temporalio.common import VersioningBehavior
from temporalio.service import TLSConfig
from temporalio.worker import Interceptor, Worker, WorkerDeploymentConfig

from .activities import commits, github_api, reviews, threads, tools
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
    pulls = PullActivities(settings)
    snapshots = SnapshotActivities(settings)
    return [
        PingActivities(identity).ping,
        pulls.list_files,
        pulls.fetch_diff,
        snapshots.snapshot,
        snapshots.delete_snapshots,
        reviews.update_check,
        reviews.publish_review,
        reviews.recover_counters,
        reviews.post_comment,
        reviews.close_pr,
        threads.resolve_threads,
        threads.close_earlier_threads,
        threads.read_thread,
        threads.reply_in_thread,
        commits.commit_fix,
        tools.glob,
        tools.grep,
        tools.read,
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
    github_api.configure(settings.app.github_app_secret)
    deployment = None
    if settings.deployment is not None:
        deployment = WorkerDeploymentConfig(
            version=settings.deployment,
            use_worker_versioning=True,
            default_versioning_behavior=VersioningBehavior.PINNED,
        )
    # The dev worker's Ctrl-C mimics AgentCore's /kill: activities stop at once, as in a crash, and resume at
    # attempt 2. An AgentCore worker only stops once idle, so its graceful shutdown rarely has anything to finish.
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

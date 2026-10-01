"""How the worker is assembled: its workflows, activities and Temporal client, shared by every entry point."""

from collections.abc import Callable, Sequence
from datetime import timedelta
from functools import cache

from temporalio.client import Client
from temporalio.common import VersioningBehavior
from temporalio.contrib.opentelemetry import OpenTelemetryPlugin
from temporalio.plugin import SimplePlugin
from temporalio.runtime import Runtime, TelemetryConfig
from temporalio.service import TLSConfig
from temporalio.worker import Interceptor, PollerBehaviorSimpleMaximum, Worker, WorkerDeploymentConfig

from . import tracing
from .activities import commits, github_api, reviews, threads, tools
from .activities.ping import PingActivities
from .activities.pulls import PullActivities
from .activities.snapshots import SnapshotActivities
from .agent_model import strands_plugin
from .settings import AppSettings, WorkerSettings
from .workflows.conversation import ConversationWorkflow
from .workflows.discussion import DiscussionWorkflow
from .workflows.fixer import FixerWorkflow
from .workflows.ping import PingWorkflow
from .workflows.pull_request import PullRequestWorkflow
from .workflows.reviewer import ReviewerWorkflow
from .workflows.synthesis import SynthesisWorkflow

# Temporal UI's Workers page shows each worker's heartbeat: every 10 s instead of the SDK's 60 s keeps it current.
WORKER_HEARTBEAT_INTERVAL = timedelta(seconds=10)
# An activity poll still open when /kill stops a session can receive a task nobody runs, lost for a heartbeat
# timeout: two polls (the SDK's default is 5) keep that loss small and still dispatch parallel tool calls.
ACTIVITY_TASK_POLLERS = PollerBehaviorSimpleMaximum(maximum=2)
# The event loop's default executor: a Bedrock stream holds one of its threads for the whole call (Strands uses
# asyncio.to_thread), next to Glob, Grep, Read, S3 and the snapshot extraction. Python's default, min(32, CPUs + 4),
# is about 6 threads on 2 vCPUs.
EXECUTOR_THREADS = 32

WORKFLOWS: list[type] = [
    PingWorkflow,
    PullRequestWorkflow,
    ReviewerWorkflow,
    SynthesisWorkflow,
    FixerWorkflow,
    DiscussionWorkflow,
    ConversationWorkflow,
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
        reviews.read_conversation,
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


def plugins(app: AppSettings, *, with_tracing: bool) -> list[SimplePlugin]:
    """Without tracing, no OpenTelemetry plugin: its interceptors and sandbox passthrough are not even installed."""
    if not with_tracing:
        return [strands_plugin(app)]
    # Temporal spans (RunWorkflow, StartActivity...) around the Strands agent spans, which nest in them.
    return [OpenTelemetryPlugin(add_temporal_spans=True), strands_plugin(app)]


async def connect(settings: WorkerSettings, identity: str, cert: bytes, key: bytes) -> Client:
    if settings.tracing:
        if settings.deployment is None:
            tracing.start(environment="dev", version=None)
        else:
            tracing.start(environment="agentcore", version=settings.deployment.build_id)
    # The Worker inherits the client's plugins: the Strands model activities, sandbox passthrough and converter.
    # No explicit data converter: StrandsPlugin installs the Pydantic converter with its failure converter
    # (Strands errors stay typed and non-retryable), and only does so over the default converter.
    return await Client.connect(
        settings.address,
        namespace=settings.namespace,
        tls=TLSConfig(client_cert=cert, client_private_key=key),
        identity=identity,
        plugins=plugins(settings.app, with_tracing=settings.tracing),
        runtime=_temporal_runtime(),
    )


@cache
def _temporal_runtime() -> Runtime:
    # Created once: each Runtime starts its own thread pool. TelemetryConfig() keeps the SDK's default logging.
    return Runtime(telemetry=TelemetryConfig(), worker_heartbeat_interval=WORKER_HEARTBEAT_INTERVAL)


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
    return Worker(
        client,
        task_queue=settings.task_queue,
        workflows=WORKFLOWS,
        activities=activities(settings.app, identity),
        interceptors=list(interceptors),
        identity=identity,
        deployment_config=deployment,
        # No grace period: an AgentCore session drains only after agentcore.DRAIN_IDLE_SECONDS without activity, so
        # it has nothing left to finish. Any other stop (/kill, maximum lifetime, Ctrl-C) cancels the activities at
        # once, and they resume at attempt 2 on another worker; the GitHub activities are idempotent.
        graceful_shutdown_timeout=timedelta(0),
        activity_task_poller_behavior=ACTIVITY_TASK_POLLERS,
    )

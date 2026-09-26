"""Everything the worker registers, shared by the entry points and the self-check."""

from collections.abc import Callable

from temporalio.client import Plugin

from . import github_client
from .activities import commits, reviews, tools
from .activities.ping import PingActivities
from .activities.pulls import PullActivities
from .activities.snapshots import SnapshotActivities
from .agent_model import strands_plugin
from .settings import AppSettings
from .workflows.fixer import FixerWorkflow
from .workflows.ping import PingWorkflow
from .workflows.pull_request import PullRequestWorkflow
from .workflows.reviewer import ReviewerWorkflow
from .workflows.synthesis import SynthesisWorkflow

WORKFLOWS: list[type] = [PingWorkflow, PullRequestWorkflow, ReviewerWorkflow, SynthesisWorkflow, FixerWorkflow]


def activities(settings: AppSettings, identity: str) -> list[Callable]:
    github_client.configure(settings.github_app_secret)
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
        reviews.post_closing_comment,
        commits.commit_changes,
        tools.glob_tool,
        tools.grep_tool,
        tools.read_tool,
    ]


def plugins(settings: AppSettings) -> list[Plugin]:
    """Client plugins. The Worker inherits them from the client: model activities, sandbox passthrough, converter."""
    return [strands_plugin(settings)]

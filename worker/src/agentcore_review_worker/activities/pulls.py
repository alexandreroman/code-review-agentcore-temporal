"""Pull request reads: the files a round reviews, and the patches of one reviewer's batch.

Both read the same comparison, pinned to two SHAs: whatever is pushed during a round, every reviewer gets
the patches of the head the round snapshotted and publishes on. PublishReview reads the pull request's
comparison at that head too.
"""

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubError
from temporalio import activity

from ..batching import partition
from ..models import BatchInput, BatchPatches, ChangedFile, ChangeSet, FilePatch, ListFilesInput
from ..settings import AppSettings
from .github_api import get, github_errors, repo_path
from .heartbeats import heartbeat_while_running

COMPARE_MAX_FILES = 300  # GitHub lists at most 300 files per comparison, without pagination


class PullActivities:
    def __init__(self, settings: AppSettings) -> None:
        self._max_parallel_agents = settings.max_parallel_agents

    @activity.defn(name="ListFiles")
    @heartbeat_while_running
    async def list_files(self, input: ListFilesInput) -> ChangeSet:
        """The real head, and the files changed since the last reviewed SHA (the whole pull request at first).

        Webhook order is not guaranteed, so the round reviews the head read here, not the signal's SHA.
        The whole pull request is the three-dot comparison from its base, like its "Files changed" tab.
        """
        pr = input.pr
        with github_errors():
            pull = await get(pr, f"{repo_path(pr)}/pulls/{pr.number}")
            diff_base, raw, unlisted = await _changed_files(pr, pull, input.since_sha)
        reviewed, excluded = partition([_changed_file(f) for f in raw])
        return ChangeSet(
            head_sha=pull["head"]["sha"],
            pr_base_sha=pull["base"]["sha"],
            diff_base=diff_base,
            files=reviewed,
            excluded=[f.path for f in excluded],
            unlisted=unlisted,
            max_parallel_agents=self._max_parallel_agents,
        )

    @activity.defn(name="FetchDiff")
    async def fetch_diff(self, input: BatchInput) -> BatchPatches:
        """The patches of a reviewer's files (the comparison ListFiles read) and the top-level tree."""
        pr = input.pr
        with github_errors():
            raw = await compared_files(pr, input.diff_base, input.head_sha)
            tree = await get(pr, f"{repo_path(pr)}/git/trees/{input.head_sha}")
        wanted = set(input.paths)
        patches = [
            FilePatch(path=f["filename"], status=f["status"], patch=f.get("patch", ""))
            for f in raw
            if f["filename"] in wanted
        ]
        names = sorted(entry["path"] + ("/" if entry["type"] == "tree" else "") for entry in tree["tree"])
        return BatchPatches(patches=patches, tree=names)


async def _changed_files(pr: PrRef, pull: dict, since: str | None) -> tuple[str, list[dict], int]:
    """The diff base, its files at the pull's head, and how many changed files GitHub left out of them.

    The delta since the last reviewed SHA when history allows it, otherwise the whole pull request.
    """
    head = pull["head"]["sha"]
    if since is not None:
        delta = await _delta_files(pr, since, head)
        if delta is not None:
            return since, delta, 0
    base = pull["base"]["sha"]
    files = await compared_files(pr, base, head)
    unlisted = 0
    if len(files) >= COMPARE_MAX_FILES:
        # changed_files counts every file of the pull request, beyond the ones the comparison lists.
        unlisted = max(pull["changed_files"] - len(files), 0)
    return base, files, unlisted


async def _delta_files(pr: PrRef, since: str, head: str) -> list[dict] | None:
    """The files changed since the last reviewed SHA, or None when the round reviews the whole pull request.

    After a force-push the last reviewed SHA is no longer an ancestor of the head: the comparison is
    then "diverged" or "behind" (or 404 once GitHub dropped the commit). A delta of COMPARE_MAX_FILES
    files may be truncated: the whole pull request, whose file count is known, is reviewed instead.
    """
    if since == head:
        return []
    try:
        comparison = await _comparison(pr, since, head)
    except GitHubError as error:
        if error.status != 404:
            raise
        comparison = {"status": "missing"}
    files = comparison.get("files", [])
    if comparison["status"] == "ahead" and len(files) < COMPARE_MAX_FILES:
        return files
    activity.logger.info(
        "no delta from %s to %s (%s, %d files): whole pull request", since, head, comparison["status"], len(files)
    )
    return None


async def compared_files(pr: PrRef, base: str, head: str) -> list[dict]:
    """The files of the three-dot comparison, at most COMPARE_MAX_FILES of them."""
    return (await _comparison(pr, base, head)).get("files", [])


async def _comparison(pr: PrRef, base: str, head: str) -> dict:
    """Three dots: the changes on the head since its merge base with the base, whatever the base did since."""
    return await get(pr, f"{repo_path(pr)}/compare/{base}...{head}")


def _changed_file(raw: dict) -> ChangedFile:
    patch = raw.get("patch")
    return ChangedFile(
        path=raw["filename"],
        patch_bytes=len(patch.encode()) if patch is not None else None,
    )

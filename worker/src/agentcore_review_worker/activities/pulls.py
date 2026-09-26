"""Pull request reads: the files a round reviews, and the patches of one reviewer's batch."""

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubError
from temporalio import activity

from ..batching import partition
from ..errors import github_errors
from ..models import BatchInput, BatchPatches, ChangedFile, ChangeSet, FilePatch, ListFilesInput
from ..settings import AppSettings
from .github_api import get, get_pages, repo_path


class PullActivities:
    def __init__(self, settings: AppSettings) -> None:
        self._max_parallel_agents = settings.max_parallel_agents

    @activity.defn(name="list_changed_files")
    async def list_changed_files(self, input: ListFilesInput) -> ChangeSet:
        """The real head, and the files changed since the last reviewed SHA (the whole pull request at first).

        Webhook order is not guaranteed, so the round reviews the head read here, not the signal's SHA.
        """
        pr = input.pr
        with github_errors():
            pull = await get(pr, f"{repo_path(pr)}/pulls/{pr.number}")
            head = pull["head"]["sha"]
            raw, diff_base = await _changed_files(pr, input.since_sha, head)
        reviewed, excluded = partition([_changed_file(f) for f in raw])
        return ChangeSet(
            head_sha=head,
            base_sha=pull["base"]["sha"],
            diff_base=diff_base,
            files=reviewed,
            excluded=[f.path for f in excluded],
            max_parallel_agents=self._max_parallel_agents,
        )

    @activity.defn(name="fetch_batch_patches")
    async def fetch_batch_patches(self, input: BatchInput) -> BatchPatches:
        """The patches of a reviewer's files (same diff as list_changed_files) and the top-level tree."""
        pr = input.pr
        with github_errors():
            raw, _ = await _changed_files(pr, input.diff_base, input.head_sha)
            tree = await get(pr, f"{repo_path(pr)}/git/trees/{input.head_sha}")
        wanted = set(input.paths)
        patches = [
            FilePatch(path=f["filename"], status=f["status"], patch=f.get("patch", ""))
            for f in raw
            if f["filename"] in wanted
        ]
        names = sorted(entry["path"] + ("/" if entry["type"] == "tree" else "") for entry in tree["tree"])
        return BatchPatches(patches=patches, tree=names)


async def _changed_files(pr: PrRef, since: str | None, head: str) -> tuple[list[dict], str | None]:
    """The delta since the last reviewed SHA when history allows it, otherwise the whole pull request.

    After a force-push the last reviewed SHA is no longer an ancestor of the head: the comparison is
    then "diverged" or "behind" (or 404 once GitHub dropped the commit), and the round reviews
    everything again.
    """
    if since == head:
        return [], since
    if since is not None:
        try:
            comparison = await get(pr, f"{repo_path(pr)}/compare/{since}...{head}")
        except GitHubError as error:
            if error.status != 404:
                raise
            comparison = {"status": "missing"}
        if comparison["status"] == "ahead":
            return comparison.get("files", []), since
        activity.logger.info("%s is not an ancestor of %s (%s): whole pull request", since, head, comparison["status"])
    return await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/files"), None


def _changed_file(raw: dict) -> ChangedFile:
    patch = raw.get("patch")
    return ChangedFile(
        path=raw["filename"],
        status=raw["status"],
        additions=raw["additions"],
        deletions=raw["deletions"],
        patch_bytes=len(patch.encode()) if patch is not None else None,
    )

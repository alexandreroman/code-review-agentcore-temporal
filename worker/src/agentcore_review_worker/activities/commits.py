"""The fixer's commit: one verified commit through the Git Data API, never a forced ref update.

No author is set, so GitHub signs the commit as the app. The Review-Fix trailer identifies a commit an
earlier attempt already pushed.
"""

from typing import NoReturn

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ..markers import fix_trailer
from ..models import CommitInput, CommitResult
from ..publishing import split_changes
from .github_api import get, github_errors, repo_path, send

REGULAR_FILE = "100644"
EXECUTABLE_FILE = "100755"


@activity.defn(name="CommitFix")
async def commit_fix(input: CommitInput) -> CommitResult:
    pr = input.pr
    trailer = fix_trailer(input.workflow_id, input.fix_number)
    accepted, rejected = split_changes(input.plan.changes)
    if rejected:
        activity.logger.warning("%s: rejected changes to %s", trailer, rejected)
    if not accepted:
        raise ApplicationError("the fix plan has no change the bot may push", type="EmptyFixPlan", non_retryable=True)
    with github_errors():
        pull = await get(pr, f"{repo_path(pr)}/pulls/{pr.number}")
        head_repo = pull["head"]["repo"]  # None once the fork is deleted
        if head_repo is None or head_repo["full_name"].lower() != f"{pr.owner}/{pr.repo}".lower():
            raise ApplicationError(
                "the pull request comes from a fork: the bot cannot push to it",
                type="ForkNotSupported",
                non_retryable=True,
            )
        branch = pull["head"]["ref"]
        pushed = await _already_pushed(pr, branch, trailer)
        if pushed is not None:
            return CommitResult(sha=pushed, rejected=rejected)
        ref = await get(pr, f"{repo_path(pr)}/git/ref/heads/{branch}")
        if ref["object"]["sha"] != input.expected_head_sha:
            await _abandon(pr, branch)
        parent = await get(pr, f"{repo_path(pr)}/git/commits/{input.expected_head_sha}")
        base_tree = parent["tree"]["sha"]
        executables = await _executable_paths(pr, base_tree)
        entries = [
            {
                "path": change.path,
                "mode": EXECUTABLE_FILE if change.path in executables else REGULAR_FILE,
                "type": "blob",
                "content": change.new_content,
            }
            for change in accepted
        ]
        tree = await send(pr, "POST", f"{repo_path(pr)}/git/trees", {"base_tree": base_tree, "tree": entries})
        commit = await send(
            pr,
            "POST",
            f"{repo_path(pr)}/git/commits",
            {
                "message": f"{input.plan.commit_message.rstrip()}\n\n{trailer}",
                "tree": tree["sha"],
                "parents": [input.expected_head_sha],
            },
        )
        try:
            await send(pr, "PATCH", f"{repo_path(pr)}/git/refs/heads/{branch}", {"sha": commit["sha"], "force": False})
        except GitHubError as error:
            if error.status == 422:  # not a fast-forward: someone pushed in between
                await _abandon(pr, branch)
            raise
    return CommitResult(sha=commit["sha"], rejected=rejected)


async def _executable_paths(pr: PrRef, tree_sha: str) -> set[str]:
    """The executable files of a tree: a fixed script keeps its executable bit, a new file is a regular one."""
    tree = await get(pr, f"{repo_path(pr)}/git/trees/{tree_sha}", {"recursive": "1"})
    return {entry["path"] for entry in tree["tree"] if entry["mode"] == EXECUTABLE_FILE}


async def _already_pushed(pr: PrRef, branch: str, trailer: str) -> str | None:
    commits = await get(pr, f"{repo_path(pr)}/commits", {"sha": branch, "per_page": 10})
    return next((c["sha"] for c in commits if trailer in c["commit"]["message"].splitlines()), None)


async def _abandon(pr: PrRef, branch: str) -> NoReturn:
    body = f"Branch `{branch}` changed while the fix was being prepared: fix abandoned. Comment `/fix` to try again."
    await send(pr, "POST", f"{repo_path(pr)}/issues/{pr.number}/comments", {"body": body})
    raise ApplicationError("branch changed, fix abandoned", type="BranchMoved", non_retryable=True)

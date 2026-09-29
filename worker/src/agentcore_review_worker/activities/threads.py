"""Finding threads on GitHub: resolve them, close an earlier run's, read one, reply in one.

Only the threads the bot opened on a finding are touched: their first comment is the bot's and carries a
finding marker.
"""

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubError
from temporalio import activity

from ..markers import extract_finding_ids, superseded_marker
from ..models import RecoveryInput, ResolveInput, ThreadComment, ThreadInput, ThreadRead, ThreadReplyInput
from ..publishing import superseded_reply
from .github_api import (
    author_login,
    body_of,
    bot_login,
    find_marked,
    get_pages,
    github,
    github_errors,
    post_once,
    repo_path,
    send,
    spaced_write,
)
from .heartbeats import heartbeat_while_running

THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        nodes { id isResolved comments(first: 1) { nodes { fullDatabaseId author { login } body } } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
RESOLVE_THREAD = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }"


@activity.defn(name="ResolveThreads")
@heartbeat_while_running
async def resolve_threads(input: ResolveInput) -> int:
    """Resolve the open finding threads of the findings a round resolved; the number resolved.

    viewerCanResolve is not checked: it reads false for an installation token that can resolve.
    """
    pr = input.pr
    wanted = set(input.finding_ids)
    resolved = 0
    with github_errors():
        for thread in await _open_finding_threads(pr):
            if not wanted & set(extract_finding_ids(_first_comment(thread)["body"])):
                continue
            try:
                await _resolve_thread(pr, thread["id"])
                resolved += 1
            except GitHubError as error:
                if error.classification.retryable:
                    raise  # a retry skips the threads already resolved
                activity.logger.warning("thread %s not resolved: %s", thread["id"], error)
    return resolved


@activity.defn(name="CloseEarlierThreads")
@heartbeat_while_running
async def close_earlier_threads(input: RecoveryInput) -> int:
    """Reply once in each open finding thread of an earlier run, then resolve it; the number closed.

    The new run's review replaces the earlier run's findings. Every attempt reads the threads and comments again,
    so a retry skips the threads already resolved and the notes already posted (their marker is keyed on the
    thread).
    """
    pr = input.pr
    closed = 0
    with github_errors():
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        for thread in await _open_finding_threads(pr):
            # The REST ID of the thread's first comment: GraphQL gives it as a BigInt serialized as a string.
            root_id = int(_first_comment(thread)["fullDatabaseId"])
            marker = superseded_marker(input.workflow_id, root_id)
            try:
                if find_marked(comments, marker) is None:
                    await send(
                        pr,
                        "POST",
                        f"{repo_path(pr)}/pulls/{pr.number}/comments/{root_id}/replies",
                        {"body": superseded_reply(marker)},
                    )
                await _resolve_thread(pr, thread["id"])
                closed += 1
            except GitHubError as error:
                if error.classification.retryable:
                    raise  # a retry skips the threads already closed
                activity.logger.warning("thread %s not closed: %s", thread["id"], error)
    return closed


@activity.defn(name="ReadThread")
@heartbeat_while_running
async def read_thread(input: ThreadInput) -> ThreadRead:
    """A finding's review thread, oldest first: GitHub points every reply's in_reply_to_id at the thread's root."""
    pr = input.pr
    with github_errors():
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        login = bot_login()
    thread = [c for c in comments if input.thread_root_id in (c["id"], c.get("in_reply_to_id"))]
    thread.sort(key=lambda c: (c["created_at"], c["id"]))
    return ThreadRead(
        comments=[ThreadComment(id=c["id"], author=author_login(c), body=body_of(c)) for c in thread],
        bot_login=login,
    )


@activity.defn(name="ReplyInThread")
@heartbeat_while_running
async def reply_in_thread(input: ThreadReplyInput) -> None:
    """Reply in a finding's thread once: a retry finds the earlier attempt's marker among the bot's comments."""
    pr = input.pr
    with github_errors():
        await post_once(
            pr,
            f"{repo_path(pr)}/pulls/{pr.number}/comments",
            f"{repo_path(pr)}/pulls/{pr.number}/comments/{input.thread_root_id}/replies",
            input.body,
            input.marker,
        )


async def _open_finding_threads(pr: PrRef) -> list[dict]:
    """The unresolved threads the bot opened on a finding."""
    bot = bot_login()
    return [thread for thread in await _review_threads(pr) if _is_open_finding_thread(thread, bot)]


def _is_open_finding_thread(thread: dict, bot: str) -> bool:
    first = _first_comment(thread)
    # fullDatabaseId is nullable in GitHub's schema: without it, the thread cannot be answered over REST.
    if thread["isResolved"] or not first or first.get("fullDatabaseId") is None:
        return False
    # GraphQL gives a bot's login without the "[bot]" suffix that REST adds; a deleted author is null.
    author = (first["author"] or {}).get("login")
    return f"{author}[bot]" == bot and bool(extract_finding_ids(first["body"]))


def _first_comment(thread: dict) -> dict:
    """A thread's first comment, or an empty dict when GraphQL returned none."""
    nodes = thread["comments"]["nodes"]
    return nodes[0] if nodes else {}


async def _review_threads(pr: PrRef) -> list[dict]:
    threads: list[dict] = []
    after = None
    while True:
        data = await github().graphql(
            pr.installation_id, THREADS_QUERY, {"owner": pr.owner, "repo": pr.repo, "number": pr.number, "after": after}
        )
        page = data["repository"]["pullRequest"]["reviewThreads"]
        threads.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return threads
        after = page["pageInfo"]["endCursor"]


async def _resolve_thread(pr: PrRef, thread_id: str) -> None:
    async with spaced_write():
        await github().graphql(pr.installation_id, RESOLVE_THREAD, {"id": thread_id})

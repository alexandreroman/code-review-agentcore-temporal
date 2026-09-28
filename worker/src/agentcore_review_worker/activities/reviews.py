"""Review side effects on GitHub: the AI Review check, the round's review, thread resolution and replies, comments
in the Conversation, the close for inactivity, the takeover of an earlier run's numbering and finding threads.

Each one is idempotent: a hidden marker or the check run's external ID identifies what an earlier
attempt already wrote.
"""

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubError
from temporalio import activity

from ..hunks import commentable_lines
from ..markers import (
    extract_finding_ids,
    last_finding_number,
    last_fix_number,
    last_round,
    round_marker,
    superseded_marker,
)
from ..models import (
    CheckInput,
    CommentInput,
    PublishInput,
    RecoveredCounters,
    RecoveryInput,
    ResolveInput,
    ThreadComment,
    ThreadInput,
    ThreadRead,
    ThreadReplyInput,
)
from ..publishing import build_review, superseded_reply
from .github_api import (
    bot_login,
    get,
    get_pages,
    github,
    github_application_error,
    github_errors,
    repo_path,
    send,
    spaced_write,
)
from .pulls import compared_files

CHECK_NAME = "AI Review"

THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        nodes { id isResolved comments(first: 1) { nodes { fullDatabaseId body } } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
RESOLVE_THREAD = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }"


@activity.defn(name="UpdateCheck")
async def set_check(input: CheckInput) -> None:
    """Create or update the AI Review check run of a round, found again by its external ID."""
    pr = input.pr
    with github_errors():
        runs = await get(
            pr,
            f"{repo_path(pr)}/commits/{input.head_sha}/check-runs",
            {"check_name": CHECK_NAME, "filter": "all", "per_page": 100},
        )
        existing = next((run for run in runs["check_runs"] if run.get("external_id") == input.external_id), None)
        body: dict = {"name": CHECK_NAME, "external_id": input.external_id, "status": input.status}
        if input.status == "completed":
            body["conclusion"] = input.conclusion
        if input.title:
            body["output"] = {"title": input.title, "summary": input.summary or input.title}
        if existing is None:
            await send(pr, "POST", f"{repo_path(pr)}/check-runs", {**body, "head_sha": input.head_sha})
        else:
            await send(pr, "PATCH", f"{repo_path(pr)}/check-runs/{existing['id']}", body)


@activity.defn(name="PublishReview")
async def publish_review(input: PublishInput) -> dict[str, int]:
    """Publish the round's single COMMENT review, unless its round marker shows it already exists.

    Inline comments are validated against the pull request's hunks at the round's head, read from the
    comparison pinned to its SHAs so that a push during the round cannot shift them. A finding on a file
    the comparison does not list (beyond its 300 files) has no known hunk and goes into the body. GitHub
    still answers 422 for the whole review if one is refused, and the workflow then republishes with
    inline=False.
    """
    pr = input.pr
    marker = round_marker(input.workflow_id, input.content.round)
    with github_errors():
        reviews = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/reviews")
        review = next((r for r in reviews if marker in (r.get("body") or "")), None)
        if review is None:
            files = await compared_files(pr, input.pr_base_sha, input.head_sha)
            commentable = {f["filename"]: commentable_lines(f.get("patch")) for f in files}
            payload = build_review(input.content, commentable, marker, inline=input.inline)
            review = await send(
                pr,
                "POST",
                f"{repo_path(pr)}/pulls/{pr.number}/reviews",
                {
                    "commit_id": input.head_sha,
                    "event": "COMMENT",
                    "body": payload.body,
                    "comments": [c.model_dump(exclude_none=True) for c in payload.comments],
                },
            )
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/reviews/{review['id']}/comments")
    return {fid: c["id"] for c in comments for fid in extract_finding_ids(c.get("body"))}


@activity.defn(name="ResolveThreads")
async def resolve_threads(input: ResolveInput) -> int:
    """Resolve the unresolved threads whose first comment carries a resolved finding's marker.

    viewerCanResolve is not checked: it reads false for an installation token that can resolve.
    """
    pr, wanted, resolved = input.pr, set(input.finding_ids), 0
    with github_errors():
        threads = await _review_threads(pr)
    for thread in threads:
        first = thread["comments"]["nodes"][:1]
        if thread["isResolved"] or not first or not wanted & set(extract_finding_ids(first[0]["body"])):
            continue
        try:
            async with spaced_write():
                await github().graphql(pr.installation_id, RESOLVE_THREAD, {"id": thread["id"]})
            resolved += 1
        except GitHubError as error:
            if error.classification.retryable:
                raise github_application_error(error) from error  # resolved threads are skipped next time
            activity.logger.warning("thread %s not resolved: %s", thread["id"], error)
    return resolved


@activity.defn(name="RecoverCounters")
async def recover_counters(input: RecoveryInput) -> RecoveredCounters:
    """Read back the numbers an earlier run of this workflow ID used; it only reads, so that it returns fast.

    A new run starts with an empty state under the same workflow ID: after a reopen, or after a failed or terminated
    run that the next event replaced. It continues the earlier run's rounds (round markers of the bot's reviews),
    findings (finding markers of the bot's comments and review bodies) and fixes (Review-Fix trailers of the pull
    request's commits).
    """
    pr, workflow_id = input.pr, input.workflow_id
    with github_errors():
        bot = bot_login()
        reviews = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/reviews")
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        commits = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/commits")
    review_bodies = [review.get("body") for review in reviews if _login(review) == bot]
    comment_bodies = [comment.get("body") for comment in comments if _login(comment) == bot]
    return RecoveredCounters(
        last_round=last_round(workflow_id, review_bodies),
        # A finding without a commentable line sits in the review body rather than in an inline comment.
        last_finding_number=last_finding_number(review_bodies + comment_bodies),
        last_fix_number=last_fix_number(workflow_id, [commit["commit"]["message"] for commit in commits]),
    )


@activity.defn(name="CloseEarlierThreads")
async def close_earlier_threads(input: RecoveryInput) -> int:
    """Reply once in each unresolved finding thread of an earlier run, then resolve it; the number closed.

    The new run does not follow the earlier run's findings: its own review replaces them. Every attempt reads the
    threads and comments again, so a retry skips the threads already resolved and the notes already posted (their
    marker is keyed on the thread). A heartbeat per thread stops an attempt that timed out before the next starts.
    """
    pr, workflow_id = input.pr, input.workflow_id
    with github_errors():
        bot = bot_login()
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        activity.heartbeat()
        threads = await _review_threads(pr)
    finding_roots = {
        comment["id"]
        for comment in comments
        if _login(comment) == bot and comment.get("in_reply_to_id") is None and extract_finding_ids(comment.get("body"))
    }
    bodies = [comment.get("body") or "" for comment in comments]
    closed = 0
    for thread in threads:
        root_id = _first_comment_id(thread)
        if thread["isResolved"] or root_id not in finding_roots:
            continue
        activity.heartbeat()
        marker = superseded_marker(workflow_id, root_id)
        try:
            if not any(marker in body for body in bodies):
                await send(
                    pr,
                    "POST",
                    f"{repo_path(pr)}/pulls/{pr.number}/comments/{root_id}/replies",
                    {"body": superseded_reply(marker)},
                )
            async with spaced_write():
                await github().graphql(pr.installation_id, RESOLVE_THREAD, {"id": thread["id"]})
            closed += 1
        except GitHubError as error:
            if error.classification.retryable:
                raise github_application_error(error) from error  # a retry skips the threads already closed
            activity.logger.warning("thread %s not closed: %s", thread["id"], error)
    return closed


def _first_comment_id(thread: dict) -> int | None:
    """The REST ID of a thread's first comment: GraphQL gives it as fullDatabaseId, a BigInt serialized as a string."""
    first = thread["comments"]["nodes"][:1]
    if not first or first[0].get("fullDatabaseId") is None:
        return None
    return int(first[0]["fullDatabaseId"])


def _login(item: dict) -> str:
    """The login of a REST review's or comment's author: "<app slug>[bot]" for the bot."""
    return (item.get("user") or {}).get("login", "")


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


@activity.defn(name="ReadThread")
async def read_thread(input: ThreadInput) -> ThreadRead:
    """A finding's review thread, oldest first: GitHub points every reply's in_reply_to_id at the thread's root."""
    pr = input.pr
    with github_errors():
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        login = bot_login()
    thread = [c for c in comments if input.thread_root_id in (c["id"], c.get("in_reply_to_id"))]
    thread.sort(key=lambda c: (c["created_at"], c["id"]))
    return ThreadRead(
        comments=[ThreadComment(id=c["id"], author=_login(c), body=c.get("body") or "") for c in thread],
        bot_login=login,
    )


@activity.defn(name="ReplyInThread")
async def post_thread_reply(input: ThreadReplyInput) -> None:
    """Reply in a finding's thread once: a retry finds the marker of the earlier attempt among the PR's comments."""
    pr = input.pr
    with github_errors():
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        if any(input.marker in (c.get("body") or "") for c in comments):
            return
        await send(
            pr,
            "POST",
            f"{repo_path(pr)}/pulls/{pr.number}/comments/{input.thread_root_id}/replies",
            {"body": input.body},
        )


@activity.defn(name="PostComment")
async def post_pr_comment(input: CommentInput) -> None:
    """Comment in the Conversation once: a retry finds the marker of the earlier attempt among its comments."""
    pr = input.pr
    with github_errors():
        comments = await get_pages(pr, f"{repo_path(pr)}/issues/{pr.number}/comments")
        if any(input.marker in (c.get("body") or "") for c in comments):
            return
        await send(pr, "POST", f"{repo_path(pr)}/issues/{pr.number}/comments", {"body": input.body})


@activity.defn(name="ClosePR")
async def close_pull_request(pr: PrRef) -> None:
    """Close the pull request; closing a closed one changes nothing, so a retry is harmless."""
    with github_errors():
        await send(pr, "PATCH", f"{repo_path(pr)}/pulls/{pr.number}", {"state": "closed"})

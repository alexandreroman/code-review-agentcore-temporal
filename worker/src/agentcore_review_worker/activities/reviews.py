"""Review side effects on GitHub: the AI Review check, the round's review, thread resolution and replies, comments
in the Conversation.

Each one is idempotent: a hidden marker or the check run's external ID identifies what an earlier
attempt already wrote.
"""

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubError
from temporalio import activity

from ..hunks import commentable_lines
from ..markers import extract_finding_ids, round_marker
from ..models import (
    CheckInput,
    CommentInput,
    PublishInput,
    ResolveInput,
    ThreadComment,
    ThreadInput,
    ThreadRead,
    ThreadReplyInput,
)
from ..publishing import build_review
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

CHECK_NAME = "AI Review"

THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        nodes { id isResolved comments(first: 1) { nodes { body } } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
RESOLVE_THREAD = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }"


@activity.defn(name="set_check")
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


@activity.defn(name="publish_review")
async def publish_review(input: PublishInput) -> dict[str, int]:
    """Publish the round's single COMMENT review, unless its round marker shows it already exists.

    Inline comments are validated against the pull request's hunks at the head; GitHub still answers
    422 for the whole review if one is refused, and the workflow then republishes with inline=False.
    """
    pr = input.pr
    marker = round_marker(input.workflow_id, input.content.round)
    with github_errors():
        reviews = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/reviews")
        review = next((r for r in reviews if marker in (r.get("body") or "")), None)
        if review is None:
            files = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/files")
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


@activity.defn(name="resolve_threads")
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


@activity.defn(name="read_thread")
async def read_thread(input: ThreadInput) -> ThreadRead:
    """A finding's review thread, oldest first: GitHub points every reply's in_reply_to_id at the thread's root."""
    pr = input.pr
    with github_errors():
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        login = bot_login()
    thread = [c for c in comments if input.thread_root_id in (c["id"], c.get("in_reply_to_id"))]
    thread.sort(key=lambda c: (c["created_at"], c["id"]))
    return ThreadRead(
        comments=[
            ThreadComment(id=c["id"], author=(c.get("user") or {}).get("login", ""), body=c.get("body") or "")
            for c in thread
        ],
        bot_login=login,
    )


@activity.defn(name="post_thread_reply")
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


@activity.defn(name="post_pr_comment")
async def post_pr_comment(input: CommentInput) -> None:
    """Comment in the Conversation once: a retry finds the marker of the earlier attempt among its comments."""
    pr = input.pr
    with github_errors():
        comments = await get_pages(pr, f"{repo_path(pr)}/issues/{pr.number}/comments")
        if any(input.marker in (c.get("body") or "") for c in comments):
            return
        await send(pr, "POST", f"{repo_path(pr)}/issues/{pr.number}/comments", {"body": input.body})

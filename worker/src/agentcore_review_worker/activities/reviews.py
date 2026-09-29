"""Review side effects on GitHub: the AI Review check, the round's review, Conversation comments, the close for
inactivity, and the recovery of an earlier run's numbering.
"""

from agentcore_review_shared.contract import PrRef
from temporalio import activity

from ..hunks import commentable_lines
from ..markers import extract_finding_ids, last_finding_numbers, last_fix_number, last_round, round_marker
from ..models import CheckInput, CommentInput, PublishInput, RecoveredCounters, RecoveryInput
from ..publishing import build_review
from .github_api import (
    author_login,
    body_of,
    bot_login,
    find_marked,
    get,
    get_pages,
    github_errors,
    post_once,
    repo_path,
    send,
)
from .heartbeats import heartbeat_while_running
from .pulls import compared_files

CHECK_NAME = "AI Review"


@activity.defn(name="UpdateCheck")
@heartbeat_while_running
async def update_check(input: CheckInput) -> None:
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
@heartbeat_while_running
async def publish_review(input: PublishInput) -> dict[str, int]:
    """Publish the round's single COMMENT review, unless the bot's review with its round marker already exists.

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
        review = find_marked(reviews, marker)
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
    return {fid: c["id"] for c in comments for fid in extract_finding_ids(body_of(c))}


@activity.defn(name="RecoverCounters")
@heartbeat_while_running
async def recover_counters(input: RecoveryInput) -> RecoveredCounters:
    """Read back the numbers an earlier run of this workflow ID used.

    Reads only; CloseEarlierThreads does the writes. A new run starts with an empty state under the same workflow
    ID: after a reopen, or after a failed or terminated run that the next event replaced. It continues the earlier
    run's rounds (round markers of the bot's reviews), findings (finding markers of the bot's comments and review
    bodies) and fixes (Review-Fix trailers of the pull request's commits).
    """
    pr, workflow_id = input.pr, input.workflow_id
    with github_errors():
        bot = bot_login()
        reviews = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/reviews")
        comments = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/comments")
        commits = await get_pages(pr, f"{repo_path(pr)}/pulls/{pr.number}/commits")
    review_bodies = [body_of(review) for review in reviews if author_login(review) == bot]
    comment_bodies = [body_of(comment) for comment in comments if author_login(comment) == bot]
    return RecoveredCounters(
        last_round=last_round(workflow_id, review_bodies),
        # A finding without a commentable line sits in the review body rather than in an inline comment.
        last_finding_numbers=last_finding_numbers(review_bodies + comment_bodies),
        last_fix_number=last_fix_number(workflow_id, [commit["commit"]["message"] for commit in commits]),
    )


@activity.defn(name="PostComment")
@heartbeat_while_running
async def post_comment(input: CommentInput) -> None:
    """Comment in the Conversation once: a retry finds the earlier attempt's marker among the bot's comments."""
    pr = input.pr
    with github_errors():
        path = f"{repo_path(pr)}/issues/{pr.number}/comments"
        await post_once(pr, path, path, input.body, input.marker)


@activity.defn(name="ClosePR")
@heartbeat_while_running
async def close_pr(pr: PrRef) -> None:
    """Close the pull request; closing a closed one changes nothing, so a retry is harmless."""
    with github_errors():
        await send(pr, "PATCH", f"{repo_path(pr)}/pulls/{pr.number}", {"state": "closed"})

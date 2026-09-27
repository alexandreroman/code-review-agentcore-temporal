"""Pure rules of the pull request lifecycle: what to do next, and how reviewer reports become open findings.

PullRequestWorkflow calls these from workflow code, so they stay deterministic and free of I/O.
"""

from typing import Literal

from agentcore_review_shared.contract import (
    Category,
    CommentPosted,
    DismissedFinding,
    Finding,
    FixRequested,
    PullRequestState,
)

from agentcore_review_worker.models import ReviewerReport, ReviewSummary, SynthesisInput, ThreadComment

Action = Literal["close", "review", "fix", "reply"]

MAX_FIX_DELIVERIES = 50
"""Fix request deliveries remembered for deduplication; redeliveries come within minutes, not 50 requests later."""

MAX_PENDING_REPLIES = 20
"""Replies queued behind a review or a fix; beyond that, the oldest are dropped."""

MAX_DISMISSED = 50
"""Dismissed findings remembered, and shown to later reviewers so they do not report them again."""

MAX_RESOLVED_THREADS = 50
"""Threads of resolved findings remembered, so that a late reply there still gets an answer."""

MAX_BOT_REPLIES_PER_THREAD = 3
"""The bot's answers in one thread before it hands over to a human: keeps a discussion from looping."""


def sort_key(finding: Finding) -> tuple:
    return (finding.severity.rank, finding.path, finding.line, finding.id)


def review_pending(state: PullRequestState) -> bool:
    return state.pending_head_sha is not None and state.pending_head_sha != state.last_reviewed_sha


def next_action(state: PullRequestState, closed: bool) -> Action | None:
    """Close first, then a pending review, then a pending fix, then a pending reply."""
    if closed:
        return "close"
    if review_pending(state):
        return "review"
    if state.pending_fix is not None:
        return "fix"
    if state.pending_replies:
        return "reply"
    return None


def record_head(state: PullRequestState, head_sha: str, reviewing_sha: str | None = None) -> bool:
    """Record a pushed head as the pending review, unless it is already reviewed, under review or pending.

    Webhooks arrive in any order and may be redelivered; the round reviews the real head anyway,
    so a pending SHA is only a trigger.
    """
    if head_sha in (state.last_reviewed_sha, state.pending_head_sha, reviewing_sha):
        return False
    state.pending_head_sha = head_sha
    return True


def record_fix_request(state: PullRequestState, request: FixRequested) -> bool:
    """Record a fix request as the pending fix, unless its webhook delivery was already seen.

    A request made while a fix is pending merges into it: the pending fix targets every open finding
    as soon as one of the requests does, otherwise the findings of all the requests' threads.
    """
    if request.delivery_id in state.fix_deliveries:
        return False
    recent = state.fix_deliveries + [request.delivery_id]
    state.fix_deliveries = recent[-MAX_FIX_DELIVERIES:]
    if state.pending_fix is None:
        state.pending_fix_roots = None if request.thread_root_id is None else [request.thread_root_id]
    elif state.pending_fix_roots is None or request.thread_root_id is None:
        state.pending_fix_roots = None
    elif request.thread_root_id not in state.pending_fix_roots:
        state.pending_fix_roots = state.pending_fix_roots + [request.thread_root_id]
    state.pending_fix = request
    return True


def record_reply(state: PullRequestState, reply: CommentPosted) -> bool:
    """Queue a reply to a finding, unless its webhook delivery was already seen; the oldest replies are dropped."""
    if reply.delivery_id in state.reply_deliveries:
        return False
    recent = state.reply_deliveries + [reply.delivery_id]
    state.reply_deliveries = recent[-MAX_FIX_DELIVERIES:]
    queued = state.pending_replies + [reply]
    state.pending_replies = queued[-MAX_PENDING_REPLIES:]
    return True


def fix_targets(state: PullRequestState, thread_root_ids: list[int] | None) -> list[Finding]:
    """Every open finding (None), or only those whose review threads the /fix requests were posted in."""
    if thread_root_ids is None:
        return list(state.open_findings)
    return [f for f in state.open_findings if f.comment_id in thread_root_ids]


def reply_target(state: PullRequestState, thread_root_id: int) -> Finding | None:
    """The open finding whose review thread starts with this comment."""
    for f in state.open_findings:
        if f.comment_id == thread_root_id:
            return f
    return None


def was_finding_thread(state: PullRequestState, thread_root_id: int) -> str | None:
    """The ID of the dismissed or resolved finding whose thread this is, so a late reply gets a short answer."""
    for dismissed in state.dismissed_findings:
        if dismissed.finding.comment_id == thread_root_id:
            return dismissed.finding.id
    return state.resolved_threads.get(thread_root_id)


def record_resolved(state: PullRequestState, finding_ids: list[str]) -> None:
    """Remember the threads of the open findings a round resolved; call it before they leave the open ones."""
    threads = dict(state.resolved_threads)
    for f in state.open_findings:
        if f.id in finding_ids and f.comment_id is not None:
            threads[f.comment_id] = f.id
    recent = list(threads.items())[-MAX_RESOLVED_THREADS:]
    state.resolved_threads = dict(recent)


def dismiss(state: PullRequestState, finding_id: str, reason: str, by: str) -> None:
    """Move an open finding to the dismissed ones; unknown IDs are ignored."""
    for f in state.open_findings:
        if f.id == finding_id:
            state.open_findings = [other for other in state.open_findings if other.id != finding_id]
            entry = DismissedFinding(finding=f, reason=reason, dismissed_by=by)
            recent = state.dismissed_findings + [entry]
            state.dismissed_findings = recent[-MAX_DISMISSED:]
            return


def reply_budget_left(bot_answers: int) -> bool:
    return bot_answers < MAX_BOT_REPLIES_PER_THREAD


def discussion_thread(
    comments: list[ThreadComment], bot_login: str, author: str, up_to_comment_id: int
) -> list[ThreadComment]:
    """What the discussion agent reads: the bot's comments and the author's, up to the reply it answers.

    Anyone else's comments stay out: on a public repository, a bystander could otherwise speak to the agent.
    """
    kept: list[ThreadComment] = []
    for comment in comments:
        if comment.author in (bot_login, author):
            kept.append(comment)
        if comment.id == up_to_comment_id:
            break
    return kept


def clean_report(report: ReviewerReport, category: Category, open_ids: list[str]) -> ReviewerReport:
    """Pin every finding to the reviewer's category and keep only resolved IDs it was asked about."""
    resolved = {raw.strip().upper() for raw in report.resolved_ids} & set(open_ids)
    return ReviewerReport(
        findings=[draft.model_copy(update={"category": category}) for draft in report.findings],
        resolved_ids=sorted(resolved),
    )


def number_findings(reports: list[ReviewerReport], next_number: int) -> tuple[list[Finding], int]:
    """Stable IDs in report order; the reports come in a fixed order (category, then batch)."""
    drafts = [draft for report in reports for draft in report.findings]
    findings = [Finding(**draft.model_dump(), id=f"F-{next_number + i:03d}") for i, draft in enumerate(drafts)]
    return findings, next_number + len(drafts)


def resolved_ids(reports: list[ReviewerReport]) -> list[str]:
    return sorted({finding_id for report in reports for finding_id in report.resolved_ids})


def apply_summary(new: list[Finding], summary: ReviewSummary) -> list[Finding]:
    """The round's findings without duplicates, in the synthesis order; unknown IDs are ignored.

    A synthesis that marks every finding as a duplicate is ignored on that point: a duplicate
    always repeats a finding that stays.
    """
    by_id = {f.id: f for f in new}
    dropped = set(summary.duplicates) & by_id.keys()
    if dropped == by_id.keys():
        dropped = set()
    ordered = [by_id[i] for i in dict.fromkeys(summary.ordered_ids) if i in by_id and i not in dropped]
    placed = {f.id for f in ordered} | dropped
    return ordered + sorted((f for f in new if f.id not in placed), key=sort_key)


def fallback_summary(input: SynthesisInput) -> ReviewSummary:
    """Deterministic stand-in for the synthesis agent: sort by severity, deduplicate by path and line."""
    most_severe: dict[tuple[str, int], Finding] = {}
    for f in input.new_findings:
        key = (f.path, f.line)
        if key not in most_severe or f.severity.rank < most_severe[key].severity.rank:
            most_severe[key] = f
    merged = sorted(most_severe.values(), key=sort_key)
    kept = {f.id for f in merged}
    if merged:
        listed = ", ".join(f"{f.id} ({f.severity})" for f in merged)
        plural = "s" if len(merged) > 1 else ""
        text = f"{len(merged)} new finding{plural} in this round, most severe first: {listed}."
    else:
        text = "No new finding in this round."
    return ReviewSummary(
        summary_markdown=text,
        ordered_ids=[f.id for f in merged],
        duplicates=[f.id for f in input.new_findings if f.id not in kept],
    )


def memo(phase: str, state: PullRequestState) -> dict[str, object]:
    """The memo shown in Temporal UI, readable even when no worker runs."""
    return {
        "state": phase,
        "round": state.round,
        "open_findings": [
            f"{f.id} {f.severity} {f.path}:{f.line} {f.title}" for f in sorted(state.open_findings, key=sort_key)
        ],
    }
